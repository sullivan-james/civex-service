"""serve(plugin_cls) is the entrypoint a plugin script calls to speak the
wire protocol over stdin/stdout. It isolates stdout first (before any
plugin code runs), then loops dispatching `describe`/`run` frames.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from pydantic import ValidationError

from civex_plugin_sdk.ctx import Ctx
from civex_plugin_sdk.errors import ConfigValidationError, PluginError
from civex_plugin_sdk.io import FrameReader, FrameWriter, isolate_stdout
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
    """Real entrypoint: isolates the actual stdout fd, then serves forever
    off real stdin. Call this (and only this) from a plugin's __main__."""
    out = isolate_stdout()
    writer = FrameWriter.for_stream(out)
    reader = FrameReader.for_stream(sys.stdin)
    serve_loop(plugin_cls, reader, writer)


def serve_loop(
    plugin_cls: "type[Plugin]", reader: FrameReader, writer: FrameWriter
) -> None:
    """The dispatch loop itself, decoupled from real stdio so it's
    unit-testable against injected reader/writer."""
    for raw in reader:
        try:
            frame = parse_frame(raw)
        except Exception as e:
            _send_error(writer, "protocol_error", str(e))
            continue

        if isinstance(frame, DescribeRequest):
            _handle_describe(plugin_cls, writer)
        elif isinstance(frame, RunRequest):
            _handle_run(plugin_cls, frame, reader, writer)
        else:
            _send_error(
                writer,
                "protocol_error",
                f"unexpected frame type on control channel: {raw.get('type')!r}",
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
        err = ConfigValidationError(str(e))
        _send_error(writer, err.code, err.message)
        return

    ctx = Ctx(writer, reader)
    try:
        outputs = plugin_cls().invoke(frame.inputs, config, ctx) or {}
    except PluginError as e:
        _send_error(writer, e.code, e.message)
        return
    except Exception as e:
        _send_error(writer, "plugin_error", str(e))
        return

    writer.send(RunResult(outputs=outputs).model_dump())


def _send_error(writer: FrameWriter, code: str, message: str) -> None:
    writer.send(ErrorFrame(error=ErrorPayload(code=code, message=message)).model_dump())
