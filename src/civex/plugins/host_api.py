"""What a plugin may ask of civex: one table.

Every function a plugin can call on the host is an entry in `HOST_API`: its
name (what goes on the wire, as an `rpc_call` method or a `call_tool` tool),
the permission action it needs (`domain.permissions`), and the call itself,
made against the run's `WorkflowContext`. The subprocess and container
runtimes dispatch through it (`dispatch`), the docs' table of `ctx` methods is
held to it by a test, and adding a function is one entry here plus the SDK
method that sends it.

**What a plugin is granted.** A plugin lists `capabilities`. Each is either a
permission action (`read`, `write_records`, `manage_files`, `delete`), which
grants every function needing it, or one function's name, which grants just
that one (the form plugins used before actions; still read). `granted()`
works out the set once, from the capabilities found at discovery, never from
what the running process says. On top of that, the services the calls go
through ask the project's own `Permissions`, so a plugin can never do what
the person running it may not.

Nothing here commits: what a run writes is kept or dropped whole by whoever
ran it (`commit` is still answered, as nothing, for plugins written before).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from civex_plugin_sdk.protocol import decode_binary, encode_binary

from civex.domain.exceptions import CapabilityDeniedError, PluginExecutionError
from civex.domain.permissions import DELETE, MANAGE_FILES, READ, WRITE_RECORDS
from civex.plugins.base import WorkflowContext

#: The permission actions a plugin may be granted. Changing the project's
#: structure or its members is not something a workflow step does.
PLUGIN_ACTIONS = (READ, WRITE_RECORDS, MANAGE_FILES, DELETE)

Call = Callable[[WorkflowContext, dict[str, Any], Path | None], dict[str, Any]]


@dataclass(frozen=True)
class HostFn:
    name: str
    #: The permission action it needs; None needs no grant (it reads and
    #: changes nothing of the project's).
    action: str | None
    call: Call
    description: str


def _record(dto: Any) -> dict[str, Any]:
    return dto.to_dict()


def _folder(scratch: Path | None) -> Path:
    if scratch is None:
        raise PluginExecutionError(
            "this run has no folder to put files in", kind="protocol_error"
        )
    return scratch


def _copy_in(ctx: WorkflowContext, sha256: str, scratch: Path | None) -> Path:
    """A read-only copy of a stored file in the run's folder (once per run:
    asked again, the same copy). A copy, never a link: a plugin writing to
    it must not change what is stored."""
    folder = _folder(scratch) / "files"
    dest = folder / sha256
    if not dest.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        ctx.copy_file(sha256, dest)
        dest.chmod(0o444)
    return dest


def _file_envelope(
    ctx: WorkflowContext, sha256: str, scratch: Path | None
) -> dict[str, Any]:
    """`get_file`'s answer: the copy in the run's folder by path, or (no
    folder: an exchange outside a run) the bytes inline."""
    if scratch is None:
        return encode_binary(ctx.get_file(sha256), None)
    return {"encoding": "path", "path": str(_copy_in(ctx, sha256, scratch))}


def _path_inside(raw: str, *roots: Path | None) -> Path:
    """`raw` resolved, if it is inside one of `roots`; refused otherwise.
    Paths come from the plugin, and the host reads what they name: a plugin
    may hand over only what it wrote where it was told to."""
    path = Path(raw).resolve()
    for root in roots:
        if root is not None and path.is_relative_to(root.resolve()):
            return path
    raise PluginExecutionError(
        f"the plugin named a file outside the run's folder: {raw}",
        kind="path_refused",
    )


#: The wire forms of a value written to a file instead of inlined.
_PATH_ENCODINGS = frozenset({"path", "ndjson_path"})


def inside_run(value: Any, *roots: Path | None) -> Any:
    """`value` unchanged, after checking every file it points at (a `path`
    or `ndjson_path` envelope, at any depth) is inside one of `roots`."""
    if isinstance(value, dict):
        if value.get("encoding") in _PATH_ENCODINGS and isinstance(
            value.get("path"), str
        ):
            _path_inside(value["path"], *roots)
        for item in value.values():
            inside_run(item, *roots)
    elif isinstance(value, list):
        for item in value:
            inside_run(item, *roots)
    return value


def _delete_record(
    ctx: WorkflowContext, args: dict[str, Any], scratch: Path | None
) -> dict[str, Any]:
    ctx.delete_record(args["record_id"])
    return {}


_FNS = [
    HostFn(
        "get_context_record",
        READ,
        lambda ctx, a, s: {"record": _record(ctx.get_context_record())},
        "The record the run is for.",
    ),
    HostFn(
        "get_context_dataset",
        READ,
        lambda ctx, a, s: {"dataset": ctx.get_context_dataset().to_dict()},
        "The collection the run's record is in.",
    ),
    HostFn(
        "get_record",
        READ,
        lambda ctx, a, s: {"record": _record(ctx.get_record(a["record_id"]))},
        "Any record, by id.",
    ),
    HostFn(
        "find_records",
        READ,
        lambda ctx, a, s: {
            "records": [
                _record(r)
                for r in ctx.find_records(
                    a["dataset_name"],
                    schema_name=a.get("schema_name"),
                    parent_record_id=a.get("parent_record_id"),
                    filters=a.get("filters"),
                    search=a.get("search"),
                    limit=a.get("limit", 50),
                    offset=a.get("offset", 0),
                )
            ]
        },
        "Records in a collection, filtered.",
    ),
    HostFn(
        "get_schema",
        READ,
        lambda ctx, a, s: {"schema": ctx.get_schema(a["name"]).to_dict()},
        "A kind of record, with its fields.",
    ),
    HostFn(
        "list_schemas",
        READ,
        lambda ctx, a, s: {"schemas": [x.to_dict() for x in ctx.list_schemas()]},
        "Every kind of record.",
    ),
    HostFn(
        "get_collection",
        READ,
        lambda ctx, a, s: {"collection": ctx.get_collection(a["name"]).to_dict()},
        "A collection, by name.",
    ),
    HostFn(
        "list_collections",
        READ,
        lambda ctx, a, s: {
            "collections": [c.to_dict() for c in ctx.list_collections()]
        },
        "Every collection.",
    ),
    HostFn(
        "get_file",
        READ,
        lambda ctx, a, s: _file_envelope(ctx, a["sha256"], s),
        "A stored file's bytes, by hash.",
    ),
    HostFn(
        "file_path",
        READ,
        lambda ctx, a, s: {"path": str(_copy_in(ctx, a["sha256"], s))},
        "A read-only copy of a stored file in the run's folder, by hash.",
    ),
    HostFn(
        "create_record",
        WRITE_RECORDS,
        lambda ctx, a, s: _record(
            ctx.create_record(
                a["dataset_name"],
                a["schema_name"],
                a["data"],
                context_record_id=a.get("context_record_id"),
            )
        ),
        "Add a record (inside the run's record unless told otherwise).",
    ),
    HostFn(
        "update_record",
        WRITE_RECORDS,
        lambda ctx, a, s: _record(ctx.update_record(a["record_id"], a["data"])),
        "Replace a record's values with these (fields left out are cleared).",
    ),
    HostFn(
        "patch_record",
        WRITE_RECORDS,
        lambda ctx, a, s: {
            "record": _record(ctx.patch_record(a["record_id"], a["fields"]))
        },
        "Change only these fields of a record; nothing is written when they "
        "already hold these values.",
    ),
    HostFn(
        "store_file",
        MANAGE_FILES,
        lambda ctx, a, s: {
            "file": ctx.store_file(
                decode_binary(inside_run(a["data"], s)), a["filename"]
            ).to_dict()
        },
        "Store bytes as a file in the run's collection.",
    ),
    HostFn(
        "store_path",
        MANAGE_FILES,
        lambda ctx, a, s: {
            "file": ctx.store_path(_path_inside(a["path"], s), a["filename"]).to_dict()
        },
        "Store the file at a path in the run's folder, in the run's collection.",
    ),
    HostFn(
        "delete_record",
        DELETE,
        _delete_record,
        "Delete a record (it can be restored from Activity).",
    ),
    HostFn(
        "commit",
        None,
        lambda ctx, a, s: {},
        "Does nothing: a run's writes are kept or dropped whole when it ends.",
    ),
]

HOST_API: dict[str, HostFn] = {fn.name: fn for fn in _FNS}


def granted(capabilities: Iterable[str]) -> frozenset[str]:
    """The functions a plugin with these `capabilities` may call: every one
    needing an action it lists, plus each it names. Functions needing no
    grant are always included."""
    listed = set(capabilities)
    return frozenset(
        fn.name
        for fn in _FNS
        if fn.action is None or fn.action in listed or fn.name in listed
    )


def unknown_capabilities(capabilities: Iterable[str]) -> list[str]:
    """Those of `capabilities` that are neither an action nor a function
    (a typo, or a function this civex doesn't have)."""
    return [c for c in capabilities if c not in PLUGIN_ACTIONS and c not in HOST_API]


def dispatch(
    ctx: WorkflowContext,
    allowed: frozenset[str],
    name: str,
    args: dict[str, Any],
    scratch_dir: Path | None,
) -> dict[str, Any]:
    """Call `name` for a plugin allowed `allowed` (from `granted`). Raises
    CapabilityDeniedError when it isn't, PluginExecutionError for a name
    this civex doesn't know."""
    fn = HOST_API.get(name)
    if fn is None:
        raise PluginExecutionError(f"unknown host function '{name}'")
    if name not in allowed:
        raise CapabilityDeniedError(name, fn.action)
    return fn.call(ctx, args, scratch_dir)
