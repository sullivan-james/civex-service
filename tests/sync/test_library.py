"""The library: workflows and plugins shared through the authority.

Nothing arrives anywhere by itself: a publish lands as text in the authority's
database, and a file is written into a project only when a person there
installs it. The authority checks what it is sent without running it, and
takes it only from devices its admin allowed, plugins only if it takes code.

Every version is kept. A workflow is pinned to the plugin versions it was
published with, and nothing that would break a workflow here is installed
unless the person says so.
"""

from __future__ import annotations

import pytest

from civex.db.models import LibraryItem
from civex.domain.exceptions import NotAllowedError, ValidationError
from civex.domain.library import ABSENT, DIFFERENT, OLDER, PLUGIN, SAME, WORKFLOW
from civex.plugins import registry

from .peers import connect, device

_BUILTIN_ONLY = """\
name: tidy-sites
description: Reads the site
triggers:
  record_created:
    schema: encounter
steps:
  - id: read
    plugin: civex.get_field
    config:
      field: site
"""


def _plugin(config_field: str = "mode", extra: str = "") -> str:
    """A shared plugin whose config has one field; changing the field's name
    is a breaking change for a workflow that sets it."""
    return f"""\
# /// script
# requires-python = ">=3.10"
# dependencies = ["civex-plugin-sdk"]
# ///
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin as PluginBase, serve

class Plugin(PluginBase):
    id = "project.shared_step"
    name = "Shared step"

    class Config(BaseModel):
        {config_field}: str = "a"{extra}

    def invoke(self, inputs, config, ctx: Ctx) -> dict:
        return {{}}

if __name__ == "__main__":
    serve(Plugin)
"""


_PLUGIN = _plugin()
_PLUGIN_COMPATIBLE = _plugin(extra="\n        loud: bool = False")
_PLUGIN_BREAKING = _plugin("style")

_USES_PLUGIN = """\
name: uses-shared
steps:
  - id: one
    plugin: project.shared_step
    config:
      mode: b
"""


@pytest.fixture()
def pair(project, authority):
    laptop = device(project, authority, "laptop")
    connect(laptop)
    phone = device(project, authority, "phone")
    connect(phone)
    return laptop, phone


def _allow(authority, name: str, mode: str | None = None) -> None:
    authority.device_keys.allow_publish(name, True)
    if mode:
        authority.sync_svc.set_library(mode)
    authority.commit()


def _project_files(ctx, folder: str) -> list[str]:
    root = ctx.sync_svc._config.civex_dir / folder
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


def _leave(ctx) -> None:
    """Take a project's plugins out of this process's registry. The registry
    is process-wide; here several projects share one process, so the computer
    a test is acting on must be the one its plugin ids point at."""
    for file, plugin_id in ctx.plugin_svc.local_plugins().items():
        registry.unregister_plugin(plugin_id)
        (ctx.plugin_svc.directory / file).unlink()


def _publish_shared(authority, laptop) -> None:
    _allow(authority, "laptop", mode="all")
    laptop.plugin_svc.save("shared_step", _PLUGIN)
    laptop.workflow_svc.save("uses-shared", _USES_PLUGIN)
    laptop.library_svc.publish(WORKFLOW, "uses-shared")


def test_a_device_publishes_only_once_the_admin_allows_it(authority, pair):
    laptop, _ = pair
    laptop.workflow_svc.save("tidy-sites", _BUILTIN_ONLY)

    with pytest.raises(NotAllowedError, match="may not publish"):
        laptop.library_svc.publish(WORKFLOW, "tidy-sites")
    assert authority.library_svc.listing() == []

    _allow(authority, "laptop")
    [item] = laptop.library_svc.publish(WORKFLOW, "tidy-sites").items
    assert (item.kind, item.name, item.published_by) == (WORKFLOW, "tidy-sites", "laptop")
    assert item.triggers == ["record_created on encounter"]

    authority.device_keys.allow_publish("laptop", False)
    authority.commit()
    with pytest.raises(NotAllowedError):
        laptop.library_svc.unpublish(WORKFLOW, "tidy-sites")


def test_a_published_workflow_is_installed_by_a_person_on_another_device(
    authority, pair
):
    laptop, phone = pair
    _allow(authority, "laptop")
    laptop.workflow_svc.save("tidy-sites", _BUILTIN_ONLY)
    laptop.library_svc.publish(WORKFLOW, "tidy-sites")

    # Nothing arrived anywhere by itself.
    assert _project_files(authority, "workflows") == []
    assert _project_files(phone, "workflows") == []
    [listed] = phone.library_svc.browse()
    assert listed.here == ABSENT and listed.content is None

    plan = phone.library_svc.plan_install(WORKFLOW, "tidy-sites")
    assert not plan.blocked and not plan.runs_code and not plan.breaks
    assert plan.warnings == ["tidy-sites runs by itself: record_created on encounter."]

    phone.library_svc.install(WORKFLOW, "tidy-sites")
    assert _project_files(phone, "workflows") == ["tidy-sites.yaml"]
    assert phone.workflow_svc.find_by_name("tidy-sites") is not None
    [listed] = phone.library_svc.browse()
    assert (listed.here, listed.local_version) == (SAME, 1)


def test_plugins_travel_only_if_the_authority_takes_code(authority, pair):
    laptop, phone = pair
    _allow(authority, "laptop")
    laptop.plugin_svc.save("shared_step", _PLUGIN)
    laptop.workflow_svc.save("uses-shared", _USES_PLUGIN)

    with pytest.raises(NotAllowedError, match="not plugins"):
        laptop.library_svc.publish(WORKFLOW, "uses-shared")
    # Alone, the workflow names a plugin the library hasn't got.
    with pytest.raises(ValidationError, match="isn't in the library"):
        laptop.library_svc.publish(WORKFLOW, "uses-shared", with_plugins=False)
    assert authority.library_svc.listing() == []

    _allow(authority, "laptop", mode="all")
    published = laptop.library_svc.publish(WORKFLOW, "uses-shared").items
    assert [(i.kind, i.name, i.provides) for i in published] == [
        (PLUGIN, "shared_step", "project.shared_step"),
        (WORKFLOW, "uses-shared", None),
    ]
    assert published[1].pins == {"project.shared_step": 1}
    assert published[0].contract and published[0].contract["id"] == "project.shared_step"
    assert _project_files(authority, "plugins") == []

    _leave(laptop)
    [plugin, workflow] = phone.library_svc.browse()
    assert workflow.needs == ["project.shared_step"] and workflow.missing == []
    plan = phone.library_svc.plan_install(WORKFLOW, "uses-shared")
    assert plan.runs_code and not plan.blocked, plan.blocked
    assert [s.path for s in plan.steps] == [
        "_civex/plugins/shared_step.py",
        "_civex/workflows/uses-shared.yaml",
    ]
    assert _project_files(phone, "plugins") == []  # planning wrote nothing
    assert not (phone.plugin_svc.directory.parent / ".staging").exists()

    done = phone.library_svc.install(WORKFLOW, "uses-shared")
    assert done.warnings == []
    assert phone.plugin_svc.local_plugins() == {"shared_step.py": "project.shared_step"}
    assert phone.workflow_svc.find_by_name("uses-shared") is not None
    assert not (phone.plugin_svc.directory.parent / ".staging").exists()


def test_a_workflow_installs_the_plugin_version_it_was_published_with(
    authority, pair
):
    laptop, phone = pair
    _publish_shared(authority, laptop)
    laptop.plugin_svc.save("shared_step", _PLUGIN_BREAKING)

    result = laptop.library_svc.publish(PLUGIN, "shared_step")
    [v2] = result.items
    assert v2.version == 2
    # The workflow in the library stays on v1, and the publisher is told why.
    [warning] = result.warnings
    assert "uses-shared v1 uses shared_step v1; v2 would break it" in warning
    assert "mode" in warning

    _leave(laptop)
    plan = phone.library_svc.plan_install(WORKFLOW, "uses-shared")
    assert [(s.item.name, s.item.version) for s in plan.steps] == [
        ("shared_step", 1),
        ("uses-shared", 1),
    ]
    phone.library_svc.install(WORKFLOW, "uses-shared")
    by_name = {i.name: i for i in phone.library_svc.browse()}
    assert (by_name["shared_step"].here, by_name["shared_step"].local_version) == (
        OLDER,
        1,
    )


def test_an_update_that_would_break_a_workflow_here_waits_to_be_forced(
    authority, pair
):
    laptop, phone = pair
    _publish_shared(authority, laptop)
    laptop.plugin_svc.save("shared_step", _PLUGIN_BREAKING)
    laptop.library_svc.publish(PLUGIN, "shared_step")
    _leave(laptop)
    phone.library_svc.install(WORKFLOW, "uses-shared")

    # Judged from the declared contract, before anything runs.
    plan = phone.library_svc.plan_install(PLUGIN, "shared_step")
    assert plan.steps[0].local_version == 1 and plan.steps[0].item.version == 2
    assert [b.split(":")[0] for b in plan.breaks] == ["uses-shared"]
    assert "mode" in plan.breaks[0]
    assert any("would break workflows here" in b for b in plan.blocked)
    with pytest.raises(ValidationError, match="break"):
        phone.library_svc.install(PLUGIN, "shared_step")
    assert "mode: str" in (phone.plugin_svc.directory / "shared_step.py").read_text()

    phone.library_svc.install(PLUGIN, "shared_step", force=True)
    assert "style: str" in (phone.plugin_svc.directory / "shared_step.py").read_text()


def test_a_compatible_update_goes_in_and_can_be_rolled_back(authority, pair):
    laptop, phone = pair
    _publish_shared(authority, laptop)
    laptop.plugin_svc.save("shared_step", _PLUGIN_COMPATIBLE)
    assert laptop.library_svc.publish(PLUGIN, "shared_step").warnings == []
    _leave(laptop)
    phone.library_svc.install(WORKFLOW, "uses-shared")

    plan = phone.library_svc.plan_install(PLUGIN, "shared_step")
    assert plan.breaks == [] and not plan.blocked
    phone.library_svc.install(PLUGIN, "shared_step")
    assert "loud" in (phone.plugin_svc.directory / "shared_step.py").read_text()

    back = phone.library_svc.plan_install(PLUGIN, "shared_step", version=1)
    assert back.warnings == ["shared_step.py goes back from v2 to v1."]
    phone.library_svc.install(PLUGIN, "shared_step", version=1)
    assert "loud" not in (phone.plugin_svc.directory / "shared_step.py").read_text()


def test_the_authority_installs_from_its_own_library_like_a_device(authority, pair):
    laptop, _ = pair
    authority.sync_svc.set_serving(True)
    _allow(authority, "laptop")
    laptop.workflow_svc.save("tidy-sites", _BUILTIN_ONLY)
    laptop.library_svc.publish(WORKFLOW, "tidy-sites")

    assert [i.here for i in authority.library_svc.browse()] == [ABSENT]
    authority.library_svc.install(WORKFLOW, "tidy-sites")
    assert _project_files(authority, "workflows") == ["tidy-sites.yaml"]

    # And it publishes as itself, whatever devices may send.
    authority.sync_svc.set_library("off")
    authority.workflow_svc.save("its-own", _BUILTIN_ONLY.replace("tidy-sites", "its-own"))
    [own] = authority.library_svc.publish(WORKFLOW, "its-own").items
    assert own.version == 1


def test_a_file_changed_here_is_never_overwritten_unless_asked(authority, pair):
    laptop, phone = pair
    _allow(authority, "laptop")
    laptop.workflow_svc.save("tidy-sites", _BUILTIN_ONLY)
    laptop.library_svc.publish(WORKFLOW, "tidy-sites")
    mine = _BUILTIN_ONLY.replace("Reads the site", "My own")
    phone.workflow_svc.save("tidy-sites", mine)

    [listed] = phone.library_svc.browse()
    assert (listed.here, listed.local_version) == (DIFFERENT, None)
    with pytest.raises(ValidationError, match="changed here"):
        phone.library_svc.install(WORKFLOW, "tidy-sites")
    assert phone.workflow_svc.get("tidy-sites")[2] == mine

    phone.library_svc.install(WORKFLOW, "tidy-sites", replace=True)
    assert phone.workflow_svc.get("tidy-sites")[2] == _BUILTIN_ONLY


def test_every_version_is_kept_and_an_older_one_installs(authority, pair):
    laptop, phone = pair
    _allow(authority, "laptop")
    laptop.workflow_svc.save("tidy-sites", _BUILTIN_ONLY)
    laptop.library_svc.publish(WORKFLOW, "tidy-sites")
    [again] = laptop.library_svc.publish(WORKFLOW, "tidy-sites").items
    assert again.version == 1  # the same text is the same version

    newer_text = _BUILTIN_ONLY.replace("Reads the site", "Reads it better")
    laptop.workflow_svc.save("tidy-sites", newer_text)
    [newer] = laptop.library_svc.publish(WORKFLOW, "tidy-sites").items
    assert newer.version == 2
    assert [h["version"] for h in newer.history] == [2, 1]

    phone.library_svc.install(WORKFLOW, "tidy-sites", version=1)
    [listed] = phone.library_svc.browse()
    assert (listed.version, listed.here, listed.local_version) == (2, OLDER, 1)
    phone.library_svc.install(WORKFLOW, "tidy-sites")  # the update: no replace needed
    assert phone.workflow_svc.get("tidy-sites")[2] == newer_text

    # Republishing an old text is that old version, not a new one.
    laptop.workflow_svc.save("tidy-sites", _BUILTIN_ONLY)
    assert laptop.library_svc.publish(WORKFLOW, "tidy-sites").items[0].version == 1

    laptop.library_svc.unpublish(WORKFLOW, "tidy-sites", version=1)
    assert [h["version"] for h in authority.library_svc.listing()[0].history] == [2]


def test_text_damaged_on_the_way_is_not_installed(authority, pair):
    laptop, phone = pair
    _allow(authority, "laptop")
    laptop.workflow_svc.save("tidy-sites", _BUILTIN_ONLY)
    laptop.library_svc.publish(WORKFLOW, "tidy-sites")
    row = authority._session.query(LibraryItem).one()
    row.content = row.content.replace("civex.get_field", "civex.save_field")
    authority.commit()

    with pytest.raises(ValidationError, match="damaged"):
        phone.library_svc.install(WORKFLOW, "tidy-sites")
    assert _project_files(phone, "workflows") == []


def test_a_plugin_that_loads_as_something_else_than_it_said_is_not_installed(
    authority, pair
):
    laptop, phone = pair
    _publish_shared(authority, laptop)
    _leave(laptop)
    row = (
        authority._session.query(LibraryItem)
        .filter_by(kind=PLUGIN)
        .one()
    )
    lying = _PLUGIN.replace("project.shared_step", "project.other_thing")
    from civex.domain.library import sha256_of

    row.content, row.sha256 = lying, sha256_of(lying)
    authority.commit()

    with pytest.raises(ValidationError, match="loads as 'project.other_thing'"):
        phone.library_svc.install(PLUGIN, "shared_step")
    assert _project_files(phone, "plugins") == []


_CONTRACT = {
    "type": "describe_result",
    "id": "project.x",
    "name": "X",
    "description": "",
    "category": "",
    "capabilities": [],
    "inputs": None,
    "outputs": None,
    "config_schema": {"type": "object", "properties": {}},
    "protocol_version": 1,
}


@pytest.mark.parametrize(
    "kind,name,content,provides,contract,problem",
    [
        (PLUGIN, "no_class", "x = 1\n", "project.x", _CONTRACT, "class named 'Plugin'"),
        (PLUGIN, "bad_python", "def (:\n", "project.x", _CONTRACT, "not valid Python"),
        (PLUGIN, "takes_builtin", _PLUGIN, "civex.get_field", _CONTRACT, "built-in"),
        (PLUGIN, "says_nothing", _PLUGIN, None, _CONTRACT, "which plugin id"),
        (PLUGIN, "no_contract", _PLUGIN, "project.x", None, "without its contract"),
        (
            PLUGIN,
            "other_contract",
            _PLUGIN,
            "project.y",
            _CONTRACT,
            "contract is for 'project.x'",
        ),
        (
            PLUGIN,
            "odd_contract",
            _PLUGIN,
            "project.x",
            {"id": "project.x"},
            "can't be read",
        ),
        (PLUGIN, "../escape", _PLUGIN, "project.x", _CONTRACT, "can't be a plugin's name"),
        (WORKFLOW, "not-yaml", "steps: [", None, None, "not a workflow"),
        (
            WORKFLOW,
            "alias-bomb",
            "a: &a [x, x]\nb: &b [*a, *a]\nname: n\nsteps: []\n",
            None,
            None,
            "aliases",
        ),
        (WORKFLOW, "too-big", "#" * (256 * 1024 + 1), None, None, "the most is"),
    ],
)
def test_the_authority_checks_what_it_is_sent_without_running_it(
    authority, kind, name, content, provides, contract, problem
):
    from civex.domain.library import LibraryItemDTO
    from civex.domain.sync import Principal

    sender = authority.sync_repo.add_device("laptop", "0" * 36, "k" * 43)
    authority.device_keys.allow_publish("laptop", True)
    authority.sync_svc.set_library("all")
    who = Principal(sender.name, sender.id, sender.device_id)
    item = LibraryItemDTO.of(kind, name, content, provides=provides, contract=contract)

    with pytest.raises(ValidationError, match=problem):
        authority.library_svc.accept(who, [item])
    assert authority.library_svc.listing() == []


def test_a_plugin_keeps_its_id_in_every_version(authority, pair):
    laptop, _ = pair
    _publish_shared(authority, laptop)
    _leave(laptop)
    laptop.plugin_svc.save(
        "shared_step", _PLUGIN.replace("project.shared_step", "project.renamed")
    )
    with pytest.raises(ValidationError, match="keeps its id"):
        laptop.library_svc.publish(PLUGIN, "shared_step")


def test_a_plugin_version_shared_workflows_use_stays_unless_forced(authority, pair):
    laptop, _ = pair
    _publish_shared(authority, laptop)

    with pytest.raises(ValidationError, match="uses-shared v1"):
        laptop.library_svc.unpublish(PLUGIN, "shared_step")
    laptop.library_svc.unpublish(PLUGIN, "shared_step", force=True)
    assert [i.name for i in authority.library_svc.listing()] == ["uses-shared"]


def test_a_project_that_shares_with_nobody_has_no_library(project):
    alone = project("alone")
    assert not alone.library_svc.sharing()
    with pytest.raises(ValidationError, match="no library"):
        alone.library_svc.browse()
