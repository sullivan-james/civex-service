"""serve(plugin_cls) is the entrypoint a plugin script calls to speak the wire protocol over stdin/stdout.

It isolates stdout first (before any plugin code runs), then loops
dispatching `describe`/`run` frames.

serve_container(plugin_cls) is the container-tier (CIVEX-149) counterpart:
same frame shapes and same fd-dup stdout isolation, but the host does one
`docker run -i <image> <mode>` per operation instead of Tier 1's persistent
`uv run` process, so `mode` ("describe" or "run") arrives as sys.argv[1]
rather than as a leading frame on stdin -- a fresh container per call is
what lets --memory/--cpus limits and CIVEX-137's timeout/kill wrapper apply
per operation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from civex_plugin_sdk.ctx import Ctx
from civex_plugin_sdk.errors import ConfigValidationError, PluginError
from civex_plugin_sdk.io import FrameReader, FrameWriter, isolate_stdout
from civex_plugin_sdk.io_convert import convert_inputs, convert_outputs
from civex_plugin_sdk.protocol import (
    DescribeRequest,
    DescribeResult,
    ErrorFrame,
    ErrorPayload,
    RunRequest,
    RunResult,
    parse_frame,
)

if TYPE_CHECKING:
    from civex_plugin_sdk.plugin import Plugin


def serve(plugin_cls: "type[Plugin]") -> None:
    """Real entrypoint: isolates the actual stdout fd, then serves forever off real stdin.

    Call this (and only this) from a plugin's __main__.
    """
    out = isolate_stdout()
    writer = FrameWriter.for_stream(out)
    reader = FrameReader.for_stream(sys.stdin)
    serve_loop(plugin_cls, reader, writer)


def serve_container(plugin_cls: "type[Plugin]") -> None:
    """Container-tier entrypoint: isolates the actual stdout fd, then performs exactly one `describe` or `run` (per sys.argv[1]) off real stdin.

    Call this (and only this) from a container-tier plugin's __main__ --
    see docs/writing-custom-plugins.md's container section.
    """
    out = isolate_stdout()
    writer = FrameWriter.for_stream(out)
    reader = FrameReader.for_stream(sys.stdin)
    mode = sys.argv[1] if len(sys.argv) > 1 else None
    serve_container_once(plugin_cls, mode, reader, writer)


def serve_container_once(
    plugin_cls: "type[Plugin]",
    mode: str | None,
    reader: FrameReader,
    writer: FrameWriter,
) -> None:
    """The single-shot dispatch itself, decoupled from real stdio/argv so it's unit-testable against injected reader/writer."""
    if mode == "describe":
        _handle_describe(plugin_cls, writer)
        return
    if mode == "run":
        try:
            raw = next(reader)
        except StopIteration:
            _send_error(
                writer,
                PluginError("no run frame received on stdin", kind="protocol_error"),
            )
            return
        try:
            frame = parse_frame(raw)
        except Exception as e:
            _send_error(writer, PluginError(str(e), kind="protocol_error"))
            return
        if not isinstance(frame, RunRequest):
            _send_error(
                writer,
                PluginError(
                    f"expected a 'run' frame, got {raw.get('type')!r}",
                    kind="protocol_error",
                ),
            )
            return
        _handle_run(plugin_cls, frame, reader, writer)
        return
    _send_error(
        writer,
        PluginError(
            f"unknown mode {mode!r}; expected 'describe' or 'run'",
            kind="protocol_error",
        ),
    )


def serve_loop(
    plugin_cls: "type[Plugin]", reader: FrameReader, writer: FrameWriter
) -> None:
    """The dispatch loop itself, decoupled from real stdio so it's unit-testable against injected reader/writer."""
    for raw in reader:
        try:
            frame = parse_frame(raw)
        except Exception as e:
            _send_error(writer, PluginError(str(e), kind="protocol_error"))
            continue

        if isinstance(frame, DescribeRequest):
            _handle_describe(plugin_cls, writer)
        elif isinstance(frame, RunRequest):
            _handle_run(plugin_cls, frame, reader, writer)
        else:
            _send_error(
                writer,
                PluginError(
                    f"unexpected frame type on control channel: {raw.get('type')!r}",
                    kind="protocol_error",
                ),
            )


def _handle_describe(plugin_cls: "type[Plugin]", writer: FrameWriter) -> None:
    writer.send(
        DescribeResult(
            id=plugin_cls.id,
            name=plugin_cls.name,
            description=plugin_cls.description,
            category=plugin_cls.category,
            capabilities=list(plugin_cls.capabilities),
            inputs=None if plugin_cls.inputs is None else list(plugin_cls.inputs),
            outputs=None if plugin_cls.outputs is None else list(plugin_cls.outputs),
            config_schema=plugin_cls.Config.model_json_schema(),
        ).model_dump()
    )


def _handle_run(
    plugin_cls: "type[Plugin]",
    frame: RunRequest,
    reader: FrameReader,
    writer: FrameWriter,
) -> None:
    try:
        config = plugin_cls.Config.model_validate(frame.config)
    except ValidationError as e:
        _send_error(writer, ConfigValidationError(str(e)))
        return

    # A plugin's cwd already *is* the host-managed, per-run scratch dir (see
    # civex-service's subprocess_runtime._spawn), so it needs no scratch path
    # of its own -- anything too large to inline is written here and crosses
    # back as an absolute path.
    scratch_dir = Path(".")
    try:
        inputs = convert_inputs(plugin_cls.inputs, frame.inputs, scratch_dir=scratch_dir)
    except Exception as e:
        # A malformed/unreadable `table`/`bytes` envelope is the host's or an
        # upstream step's fault, not this plugin author's -- classified as a
        # protocol error rather than reported as if invoke() had failed.
        _send_error(
            writer,
            PluginError(f"could not decode step inputs: {e}", kind="protocol_error"),
        )
        return

    ctx = Ctx(writer, reader)
    try:
        outputs = plugin_cls().invoke(inputs, config, ctx) or {}
        # Declared `table`/`bytes` outputs become the always-JSON-safe wire
        # envelope here, so an author can return a DataFrame or raw bytes
        # from invoke() and the frame below still serializes.
        outputs = convert_outputs(plugin_cls.outputs, outputs, scratch_dir=scratch_dir)
    except PluginError as e:
        _send_error(writer, e)
        return
    except Exception as e:
        # An exception the plugin didn't classify. Reported as the generic
        # kind and never as retryable -- the SDK has no basis to guess, and
        # guessing wrong in that direction means re-running a permanently
        # broken step.
        _send_error(writer, PluginError(str(e)))
        return

    writer.send(RunResult(outputs=outputs).model_dump())


def _send_error(writer: FrameWriter, error: PluginError) -> None:
    writer.send(
        ErrorFrame(
            error=ErrorPayload(
                kind=error.kind, message=error.message, retryable=error.retryable
            )
        ).model_dump()
    )
