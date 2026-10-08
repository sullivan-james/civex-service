"""The library: workflows and plugins shared through the authority.

Nothing arrives anywhere by itself: a publish lands as text in the authority's
database, and a file is written into a project only when a person there
installs it. The authority checks what it is sent without running it, and
takes it only from devices its admin allowed, plugins only if it takes code.
"""

from __future__ import annotations

import pytest

from civex.db.models import LibraryItem
from civex.domain.exceptions import NotAllowedError, ValidationError
from civex.domain.library import ABSENT, DIFFERENT, PLUGIN, SAME, WORKFLOW

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

_PLUGIN = """\
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
        pass

    def invoke(self, inputs, config, ctx: Ctx) -> dict:
        return {}

if __name__ == "__main__":
    serve(Plugin)
"""

_USES_PLUGIN = """\
name: uses-shared
steps:
  - id: one
    plugin: project.shared_step
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


def test_a_device_publishes_only_once_the_admin_allows_it(authority, pair):
    laptop, _ = pair
    laptop.workflow_svc.save("tidy-sites", _BUILTIN_ONLY)

    with pytest.raises(NotAllowedError, match="may not publish"):
        laptop.library_svc.publish(WORKFLOW, "tidy-sites")
    assert authority.library_svc.listing() == []

    _allow(authority, "laptop")
    [item] = laptop.library_svc.publish(WORKFLOW, "tidy-sites")
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
    assert not plan.blocked and not plan.runs_code
    assert plan.warnings == ["tidy-sites runs by itself: record_created on encounter."]

    phone.library_svc.install(WORKFLOW, "tidy-sites")
    assert _project_files(phone, "workflows") == ["tidy-sites.yaml"]
    assert phone.workflow_svc.find_by_name("tidy-sites") is not None
    assert phone.library_svc.browse()[0].here == SAME


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
    published = laptop.library_svc.publish(WORKFLOW, "uses-shared")
    assert [(i.kind, i.name, i.provides) for i in published] == [
        (PLUGIN, "shared_step", "project.shared_step"),
        (WORKFLOW, "uses-shared", None),
    ]
    assert _project_files(authority, "plugins") == []

    [plugin, workflow] = phone.library_svc.browse()
    assert workflow.needs == ["project.shared_step"] and workflow.missing == []
    plan = phone.library_svc.plan_install(WORKFLOW, "uses-shared")
    assert plan.runs_code
    assert [s.path for s in plan.steps] == [
        "_civex/plugins/shared_step.py",
        "_civex/workflows/uses-shared.yaml",
    ]
    assert _project_files(phone, "plugins") == []  # planning wrote nothing

    done = phone.library_svc.install(WORKFLOW, "uses-shared")
    assert done.warnings == []
    assert phone.plugin_svc.local_plugins() == {"shared_step.py": "project.shared_step"}
    assert phone.workflow_svc.find_by_name("uses-shared") is not None


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
    [own] = authority.library_svc.publish(WORKFLOW, "its-own")
    assert own.version == 1


def test_installing_never_overwrites_a_different_file_unless_asked(authority, pair):
    laptop, phone = pair
    _allow(authority, "laptop")
    laptop.workflow_svc.save("tidy-sites", _BUILTIN_ONLY)
    laptop.library_svc.publish(WORKFLOW, "tidy-sites")
    mine = _BUILTIN_ONLY.replace("Reads the site", "My own")
    phone.workflow_svc.save("tidy-sites", mine)

    assert phone.library_svc.browse()[0].here == DIFFERENT
    with pytest.raises(ValidationError, match="different contents"):
        phone.library_svc.install(WORKFLOW, "tidy-sites")
    assert phone.workflow_svc.get("tidy-sites")[2] == mine

    phone.library_svc.install(WORKFLOW, "tidy-sites", replace=True)
    assert phone.workflow_svc.get("tidy-sites")[2] == _BUILTIN_ONLY


def test_a_new_version_replaces_the_old_and_counts_up(authority, pair):
    laptop, phone = pair
    _allow(authority, "laptop")
    laptop.workflow_svc.save("tidy-sites", _BUILTIN_ONLY)
    laptop.library_svc.publish(WORKFLOW, "tidy-sites")
    [again] = laptop.library_svc.publish(WORKFLOW, "tidy-sites")
    assert again.version == 1  # the same text changes nothing

    laptop.workflow_svc.save("tidy-sites", _BUILTIN_ONLY.replace("site", "depth"))
    [newer] = laptop.library_svc.publish(WORKFLOW, "tidy-sites")
    assert newer.version == 2


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


@pytest.mark.parametrize(
    "kind,name,content,provides,problem",
    [
        (PLUGIN, "no_class", "x = 1\n", "project.x", "class named 'Plugin'"),
        (PLUGIN, "bad_python", "def (:\n", "project.x", "not valid Python"),
        (PLUGIN, "takes_builtin", _PLUGIN, "civex.get_field", "built-in"),
        (PLUGIN, "says_nothing", _PLUGIN, None, "which plugin id"),
        (PLUGIN, "../escape", _PLUGIN, "project.x", "can't be a plugin's name"),
        (WORKFLOW, "not-yaml", "steps: [", None, "not a workflow"),
        (
            WORKFLOW,
            "alias-bomb",
            "a: &a [x, x]\nb: &b [*a, *a]\nname: n\nsteps: []\n",
            None,
            "aliases",
        ),
        (WORKFLOW, "too-big", "#" * (256 * 1024 + 1), None, "the most is"),
    ],
)
def test_the_authority_checks_what_it_is_sent_without_running_it(
    authority, kind, name, content, provides, problem
):
    from civex.domain.library import LibraryItemDTO
    from civex.domain.sync import Principal

    sender = authority.sync_repo.add_device("laptop", "0" * 36, "k" * 43)
    authority.device_keys.allow_publish("laptop", True)
    authority.sync_svc.set_library("all")
    who = Principal(sender.name, sender.id, sender.device_id)
    item = LibraryItemDTO.of(kind, name, content, provides=provides)

    with pytest.raises(ValidationError, match=problem):
        authority.library_svc.accept(who, [item])
    assert authority.library_svc.listing() == []


def test_a_plugin_shared_workflows_use_stays_unless_forced(authority, pair):
    laptop, _ = pair
    _allow(authority, "laptop", mode="all")
    laptop.plugin_svc.save("shared_step", _PLUGIN)
    laptop.workflow_svc.save("uses-shared", _USES_PLUGIN)
    laptop.library_svc.publish(WORKFLOW, "uses-shared")

    with pytest.raises(ValidationError, match="uses-shared"):
        laptop.library_svc.unpublish(PLUGIN, "shared_step")
    laptop.library_svc.unpublish(PLUGIN, "shared_step", force=True)
    assert [i.name for i in authority.library_svc.listing()] == ["uses-shared"]


def test_a_project_that_shares_with_nobody_has_no_library(project):
    alone = project("alone")
    with pytest.raises(ValidationError, match="no library"):
        alone.library_svc.browse()
