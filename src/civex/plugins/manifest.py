"""A plugin script's contract, declared in its own header.

A custom plugin says what it is in the PEP 723 block at the top of the file,
under `[tool.civex]`, beside the dependencies uv reads:

    # /// script
    # requires-python = ">=3.10"
    # dependencies = ["civex-plugin-sdk"]
    #
    # [tool.civex]
    # id = "project.tidy"
    # name = "Tidy"
    # capabilities = ["read", "write_records"]
    # config_schema = "{...}"
    #
    # [[tool.civex.inputs]]
    # name = "files"
    # type = "files"
    # ///

So civex learns a plugin's id, capabilities, inputs, outputs and config
without running it: discovery and the library's checks read text. The header
is written from the plugin's own `describe` answer (`civex plugin check
--write`, and the AI authoring tool on save), never by hand, and a plugin
whose code no longer says what its header does is refused when its process
starts (`differences`, asked by `launchers.UvLauncher.check`). A script with
no `[tool.civex]` is described by running it, as before.

Pure: text in, text or data out.
"""

from __future__ import annotations

import json
import re
import tomllib
from typing import Any

from civex_plugin_sdk.protocol import DescribeResult

_BLOCK = re.compile(
    r"(?m)^# /// script\s*$\n(?P<content>(?:^#(?: .*)?$\n)*?)^# ///\s*$"
)

#: What must agree between a header and the code's own `describe` for the
#: code to be run under that header. The description and name are words for
#: people and may drift without harm.
CONTRACT_KEYS = ("id", "capabilities", "inputs", "outputs", "config_schema")


def _script_block(text: str) -> re.Match[str] | None:
    return _BLOCK.search(text)


def _block_lines(content: str) -> list[str]:
    """The block's TOML, one line each, without the leading `# `."""
    out = []
    for line in content.splitlines():
        out.append(line[2:] if line.startswith("# ") else line[1:])
    return out


def read(text: str) -> DescribeResult | None:
    """The contract a script declares under `[tool.civex]`, or None when it
    declares none. Raises ValueError when the header is there but broken."""
    match = _script_block(text)
    if match is None:
        return None
    try:
        data = tomllib.loads("\n".join(_block_lines(match["content"])))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"the script header isn't valid TOML: {e}") from e
    declared = data.get("tool", {}).get("civex")
    if not declared:
        return None
    declared = dict(declared)
    schema = declared.get("config_schema")
    if isinstance(schema, str):
        try:
            declared["config_schema"] = json.loads(schema)
        except ValueError as e:
            raise ValueError(f"[tool.civex] config_schema isn't JSON: {e}") from e
    declared.setdefault("type", "describe_result")
    try:
        return DescribeResult.model_validate(declared)
    except ValueError as e:
        raise ValueError(f"[tool.civex] doesn't describe a plugin: {e}") from e


def _toml_string(value: str) -> str:
    # A JSON string without ASCII escaping is a valid TOML basic string.
    return json.dumps(value, ensure_ascii=False)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"can't write {type(value).__name__} in a plugin header")


def render(described: DescribeResult) -> list[str]:
    """`[tool.civex]` for `described`, as TOML lines (without `# `)."""
    lines = [
        "[tool.civex]",
        f"id = {_toml_string(described.id)}",
        f"name = {_toml_string(described.name)}",
    ]
    if described.description:
        lines.append(f"description = {_toml_string(described.description)}")
    lines += [
        f"category = {_toml_string(described.category)}",
        f"capabilities = {_toml_value(list(described.capabilities))}",
        f"protocol_version = {described.protocol_version}",
        "config_schema = "
        + _toml_string(json.dumps(described.config_schema, separators=(",", ":"))),
    ]
    tables: list[str] = []
    for key in ("inputs", "outputs"):
        specs = getattr(described, key)
        if specs is None:
            continue  # no declaration: absent, not empty
        if not specs:
            lines.append(f"{key} = []")
            continue
        for spec in specs:
            tables += ["", f"[[tool.civex.{key}]]"]
            for field, value in spec.model_dump().items():
                tables.append(f"{field} = {_toml_value(value)}")
    return lines + tables


def write(text: str, described: DescribeResult) -> str:
    """`text` with its `[tool.civex]` replaced by `described` (added at the
    end of the script block, which is made if there is none). Everything
    else in the file is left as it is."""
    header = render(described)
    match = _script_block(text)
    if match is None:
        block = [
            "/// script",
            'dependencies = ["civex-plugin-sdk"]',
            "",
            *header,
            "///",
        ]
        rendered = "".join(f"# {line}\n" if line else "#\n" for line in block)
        if text.startswith("#!"):
            first, _, rest = text.partition("\n")
            return f"{first}\n{rendered}{rest}"
        return rendered + text
    kept: list[str] = []
    table = ""
    for line in _block_lines(match["content"]):
        stripped = line.strip()
        if stripped.startswith("["):
            table = stripped.strip("[]").strip()
        if table == "tool.civex" or table.startswith("tool.civex."):
            continue
        kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    body = [*kept, "", *header]
    rendered = "".join(f"# {line}\n" if line else "#\n" for line in body)
    return text[: match.start("content")] + rendered + text[match.end("content") :]


def differences(declared: DescribeResult, described: DescribeResult) -> list[str]:
    """What the code says differently from its header (`CONTRACT_KEYS`), in
    words; empty when they agree."""
    out = []
    a, b = declared.model_dump(), described.model_dump()
    for key in CONTRACT_KEYS:
        if a.get(key) != b.get(key):
            out.append(
                f"{key}: the header says {a.get(key)!r}, the code {b.get(key)!r}"
            )
    return out
