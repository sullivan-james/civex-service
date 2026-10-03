"""Every `civex <words>` example in a fenced code block under docs/ or README.md
must resolve against the live Typer app.

This is the drift check that would have caught every phantom command that has
ever shipped in the docs: commands documented as "not yet implemented" when
they were, and commands renamed or deleted (`civex dataset` -> `civex
collection`, `civex commit`/`civex log`, `civex workflow drain`) that kept
appearing in prose long after the code moved on.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

import typer.main

from civex.main import app as cli_app

REPO_ROOT = Path(__file__).resolve().parents[2]

_FENCE_RE = re.compile(r"^\s*```")
_CIVEX_RE = re.compile(r"\bcivex\b(?=\s|$)")
_ALL_CAPS_RE = re.compile(r"^[A-Z][A-Z0-9_-]*$")


def _doc_files() -> list[Path]:
    files = sorted((REPO_ROOT / "docs").rglob("*.md"))
    files.append(REPO_ROOT / "README.md")
    return files


def _code_blocks(text: str) -> list[list[tuple[int, str]]]:
    """Fenced code blocks as lists of (1-based line number, raw line)."""
    blocks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    in_block = False
    for line_no, line in enumerate(text.splitlines(), start=1):
        if _FENCE_RE.match(line):
            if in_block:
                blocks.append(current)
                current = []
            in_block = not in_block
            continue
        if in_block:
            current.append((line_no, line))
    return blocks


def _logical_lines(block: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Join `\\`-continued lines within a block into single logical lines."""
    result: list[tuple[int, str]] = []
    start_line = None
    buf = ""
    for line_no, text in block:
        stripped = text.rstrip()
        if start_line is None:
            start_line = line_no
        if stripped.endswith("\\"):
            buf += stripped[:-1] + " "
            continue
        buf += stripped
        result.append((start_line, buf))
        start_line, buf = None, ""
    if start_line is not None:
        result.append((start_line, buf))
    return result


def _strip_comment(line: str) -> str:
    match = re.search(r"(?<!\S)#", line)
    return line[: match.start()] if match else line


def _is_placeholder(token: str) -> bool:
    if token[:1] in "<{[":
        return True
    core = token.strip(":,.")
    return bool(core) and bool(_ALL_CAPS_RE.match(core))


def _invocations(text: str) -> list[tuple[int, str]]:
    """(line_no, text-after-the-word-'civex') for every civex example in `text`."""
    found: list[tuple[int, str]] = []
    for block in _code_blocks(text):
        for line_no, logical in _logical_lines(block):
            for segment in re.split(r"&&|\|\||;|\|", _strip_comment(logical)):
                match = _CIVEX_RE.search(segment)
                if match:
                    found.append((line_no, segment[match.end() :].strip()))
    return found


def _resolve(rest: str) -> tuple[bool, str | None, list[str], Any]:
    """Walk the Typer command tree following `rest`'s tokens.

    Stops at the first `-`-prefixed token, a placeholder (`<name>`, `NAME`,
    `{id}`, `[...]`), or once a leaf command (no further subcommands) is
    reached. Returns (resolved, failing_token, path_consumed, node_at_failure).
    """
    node = typer.main.get_command(cli_app)
    path: list[str] = []
    for token in rest.split():
        if token.startswith("-") or _is_placeholder(token):
            break
        if not hasattr(node, "commands"):
            break
        if token not in node.commands:
            return False, token, path, node
        node = node.commands[token]
        path.append(token)
    return True, None, path, node


def test_civex_cli_examples_in_docs_resolve() -> None:
    failures = []
    for path in _doc_files():
        rel = path.relative_to(REPO_ROOT)
        for line_no, rest in _invocations(path.read_text()):
            ok, bad_token, path_so_far, node = _resolve(rest)
            if ok:
                continue
            prefix = f"civex {' '.join(path_so_far)}".strip()
            suggestion = ""
            if hasattr(node, "commands"):
                close = difflib.get_close_matches(bad_token, node.commands.keys(), n=1)
                if close:
                    suggestion = f" — did you mean `{prefix} {close[0]}`?"
            failures.append(
                f"{rel}:{line_no}: `civex {rest}` — "
                f"'{bad_token}' is not a subcommand of `{prefix}`{suggestion}"
            )

    assert not failures, "Documented CLI examples that don't resolve:\n" + "\n".join(
        failures
    )
