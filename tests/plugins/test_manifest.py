"""A plugin's contract declared in its own header (`civex.plugins.manifest`):
read without running it, written from what the code says, and held to the
code when its process starts."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from civex_plugin_sdk.plugin_base import IOSpec
from civex_plugin_sdk.protocol import DescribeResult

from civex.domain.exceptions import PluginExecutionError
from civex.plugins import manifest, registry, runtime
from civex.plugins import subprocess_runtime as rt
from civex.plugins.launchers import UvLauncher

DESCRIBED = DescribeResult(
    id="project.tidy",
    name="Tidy",
    description='Says "hi" — and more',
    category="cleaning",
    capabilities=["read", "write_records"],
    inputs=[IOSpec(name="files", type="files", description="to tidy")],
    outputs=[],
    config_schema={"properties": {"n": {"type": "integer", "default": 3}}},
)

SCRIPT = """\
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["civex-plugin-sdk"]
# ///
print("body")
"""


def test_a_header_round_trips_through_the_file() -> None:
    text = manifest.write(SCRIPT, DESCRIBED)
    assert manifest.read(text) == DESCRIBED
    assert text.startswith("#!/usr/bin/env python3\n# /// script\n")
    assert '# dependencies = ["civex-plugin-sdk"]' in text  # the rest is kept
    assert text.endswith('# ///\nprint("body")\n')


def test_writing_again_replaces_the_header_rather_than_adding_one() -> None:
    once = manifest.write(SCRIPT, DESCRIBED)
    changed = DESCRIBED.model_copy(update={"capabilities": ["read"]})
    twice = manifest.write(once, changed)
    assert twice.count("[tool.civex]") == 1
    assert manifest.read(twice).capabilities == ["read"]  # type: ignore[union-attr]


def test_undeclared_inputs_stay_undeclared_and_empty_ones_empty() -> None:
    described = DESCRIBED.model_copy(update={"inputs": None, "outputs": []})
    read = manifest.read(manifest.write(SCRIPT, described))
    assert read is not None and read.inputs is None and read.outputs == []


def test_a_script_with_no_block_gets_one_after_its_shebang() -> None:
    text = manifest.write("#!/usr/bin/env python3\nprint(1)\n", DESCRIBED)
    assert text.startswith("#!/usr/bin/env python3\n# /// script\n")
    assert manifest.read(text) == DESCRIBED


def test_no_header_is_none_and_a_broken_one_says_so() -> None:
    assert manifest.read(SCRIPT) is None
    assert manifest.read("print(1)\n") is None
    broken = SCRIPT.replace("# ///\nprint", "# [tool.civex]\n# id = \n# ///\nprint")
    with pytest.raises(ValueError, match="TOML"):
        manifest.read(broken)


def test_differences_name_what_the_code_says_otherwise() -> None:
    code = DESCRIBED.model_copy(update={"capabilities": ["read", "delete"]})
    (problem,) = manifest.differences(DESCRIBED, code)
    assert problem.startswith("capabilities:")
    # Words for people may change without harm.
    reworded = DESCRIBED.model_copy(update={"description": "other words"})
    assert manifest.differences(DESCRIBED, reworded) == []


# -- discovery and the check when a process starts ----------------------------

PLUGIN = """\
# /// script
# dependencies = ["civex-plugin-sdk"]
# ///
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin as PluginBase, serve

class Plugin(PluginBase):
    id = "project.header_test"
    name = "Header test"
    capabilities = CAPS

    class Config(BaseModel):
        pass

    def invoke(self, inputs, config, ctx: Ctx) -> dict:
        return {"ok": True}

if __name__ == "__main__":
    serve(Plugin)
"""


@pytest.fixture
def plain_python(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scripts run by this venv's Python, not uv."""
    monkeypatch.setattr(rt, "_build_command", lambda uv, p: [sys.executable, str(p)])
    monkeypatch.setattr(rt, "find_uv_binary", lambda: "uv")
    monkeypatch.setattr(rt, "lock_plugin", lambda p: None)


def _plugin(tmp_path: Path, caps: list[str], header_caps: list[str] | None) -> Path:
    plugins = tmp_path / "plugins"
    plugins.mkdir(exist_ok=True)
    path = plugins / "header_test.py"
    text = PLUGIN.replace("CAPS", repr(caps))
    if header_caps is not None:
        declared = DescribeResult(
            id="project.header_test",
            name="Header test",
            capabilities=header_caps,
            inputs=None,
            outputs=None,
            config_schema={"properties": {}, "title": "Config", "type": "object"},
        )
        text = manifest.write(text, declared)
    path.write_text(text)
    return path


def test_a_declared_plugin_is_discovered_without_running_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plain_python: None
) -> None:
    path = _plugin(tmp_path, ["read"], header_caps=["read"])
    monkeypatch.setattr(
        rt, "describe_plugin", lambda *a, **k: pytest.fail("described by running it")
    )
    registry.discover_user_plugins(path.parent)
    registration = registry.get_plugin("project.header_test")
    assert registration is not None and registration.capabilities == ["read"]
    registry.unregister_plugin("project.header_test")


def test_a_plugin_whose_code_agrees_with_its_header_runs(
    tmp_path: Path, plain_python: None
) -> None:
    path = _plugin(tmp_path, ["read"], header_caps=["read"])
    launcher = UvLauncher(path, declared=registry._declared(path))
    assert runtime.run(launcher, {}, {}, None, ["read"], 20).outputs == {"ok": True}  # type: ignore[arg-type]


def test_a_plugin_whose_code_outgrew_its_header_is_refused(
    tmp_path: Path, plain_python: None
) -> None:
    """The header grants read; the code now asks for delete too."""
    path = _plugin(tmp_path, ["read", "delete"], header_caps=["read"])
    launcher = UvLauncher(path, declared=registry._declared(path))
    with pytest.raises(PluginExecutionError, match="civex plugin check --write") as e:
        runtime.run(launcher, {}, {}, None, ["read"], 20)  # type: ignore[arg-type]
    assert e.value.kind == "contract_mismatch"


def test_the_library_runs_the_code_rather_than_trust_a_header(
    tmp_path: Path, plain_python: None
) -> None:
    path = _plugin(tmp_path, ["read", "delete"], header_caps=["read"])
    assert registry.describe_file(path).capabilities == ["read"]  # the header
    with pytest.raises(ValueError, match="doesn't do what its header says"):
        registry.describe_code(path)


# -- lockfiles ----------------------------------------------------------------


def test_a_locked_script_runs_from_its_lock_without_the_sdk_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rt, "_sdk_find_links_dir", lambda: None)
    monkeypatch.setattr(rt, "_installed_sdk_version", lambda: "9.9.9")
    path = tmp_path / "p.py"
    path.write_text("print(1)\n")
    assert "--with" in rt._build_command("uv", path)
    rt.lockfile_of(path).write_text("version = 1\n")
    assert rt._build_command("uv", path) == ["uv", "run", "--no-project", str(path)]


def test_nothing_is_locked_in_a_development_checkout(tmp_path: Path) -> None:
    """Plugins there resolve the SDK from a wheel built per process."""
    if rt._sdk_find_links_dir() is None:
        pytest.skip("not a development checkout")
    path = tmp_path / "p.py"
    path.write_text("print(1)\n")
    assert rt.lock_plugin(path) is None
    assert not rt.lockfile_of(path).exists()


@pytest.mark.skipif(__import__("shutil").which("uv") is None, reason="needs uv")
def test_locking_writes_the_lockfile_beside_the_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rt, "_sdk_find_links_dir", lambda: None)
    path = tmp_path / "p.py"
    path.write_text("# /// script\n# dependencies = []\n# ///\nprint(1)\n")
    lock = rt.lock_plugin(path)
    assert lock == tmp_path / "p.py.lock" and lock.is_file()
