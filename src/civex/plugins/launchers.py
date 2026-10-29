"""How each kind of plugin is started (`runtime.Launcher`).

A tier is only this: what starts the plugin and how it is stopped. Driving
the protocol, the pool of kept workers and the timeout are `runtime`'s, the
same for every launcher, so adding a way to run plugins (a remote runner,
WASM) is one class here.

- `UvLauncher`: a Python script in `_civex/plugins/`, run by `uv run` with
  the dependencies its PEP 723 header names, in a sandboxed subprocess.
- `CommandLauncher`: any command speaking the protocol on stdin/stdout, in
  the same sandbox (what `UvLauncher` is, with uv's command line).
- `DockerLauncher`: an image, one container per request (`docker run -i`).
- `InProcessLauncher`: a built-in `Plugin` class, served by the SDK's own
  `serve_loop` on a thread in this process over in-memory frame streams.
"""

from __future__ import annotations

import hashlib
import queue
import shutil
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Callable, Hashable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, cast

from civex_plugin_sdk.io import FrameReader, FrameWriter
from civex_plugin_sdk.serve import serve_loop

from civex.plugins.base import PluginTier
from civex.plugins.runtime import Connection, Launcher

if TYPE_CHECKING:
    from civex_plugin_sdk.plugin import Plugin


# -- a process -----------------------------------------------------------------


class ProcessConnection(Connection):
    """A child process speaking the protocol on its stdin/stdout."""

    def __init__(
        self,
        proc: subprocess.Popen,
        scratch_dir: Path | None,
        kill: Callable[[], None] | None = None,
        remove_scratch: bool = True,
    ) -> None:
        from civex.plugins import subprocess_runtime as sr

        self.proc = proc
        self.scratch_dir = scratch_dir
        # Pipes are always text streams here (Popen's type can't say so).
        self.writer = FrameWriter.for_stream(cast(TextIO, proc.stdin))
        self.reader = FrameReader.for_stream(cast(TextIO, proc.stdout))
        self._kill = kill or (lambda: sr._kill_process_group(proc))
        self._remove_scratch = remove_scratch

    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self) -> None:
        self._kill()

    def close(self) -> None:
        from civex.plugins import subprocess_runtime as sr

        try:
            sr._ensure_terminated(self.proc, kill=self._kill)
        finally:
            if self._remove_scratch and self.scratch_dir is not None:
                shutil.rmtree(self.scratch_dir, ignore_errors=True)

    def death_message(self) -> str:
        from civex.plugins import subprocess_runtime as sr

        return sr._dead_process_message(self.proc)

    def relaying(self):  # type: ignore[override]
        from civex.plugins import subprocess_runtime as sr

        return sr._relaying(self.proc)


class CommandLauncher(Launcher):
    """A command speaking the protocol, started in the plugin sandbox: a
    throwaway working folder, a minimal environment, its own process group
    (`subprocess_runtime._spawn`). Kept between runs."""

    tier = PluginTier.SUBPROCESS

    def __init__(self, argv: list[str], key: Hashable | None = None) -> None:
        self._argv = argv
        self._key = key if key is not None else tuple(argv)

    @property
    def key(self) -> Hashable:
        return self._key

    def argv(self) -> list[str]:
        return self._argv

    def start(self, mode: str) -> Connection:
        from civex.plugins import subprocess_runtime as sr

        scratch_dir = Path(tempfile.mkdtemp(prefix="civex-plugin-"))
        try:
            proc = sr._spawn(self.argv(), scratch_dir)
        except BaseException:
            shutil.rmtree(scratch_dir, ignore_errors=True)
            raise
        return ProcessConnection(proc, scratch_dir)


class UvLauncher(CommandLauncher):
    """A plugin script, run by `uv run --no-project` (`_build_command`).
    Its key is the command line and the file's contents, so an edited
    plugin never reaches a process started from the old one."""

    def __init__(self, plugin_path: Path) -> None:
        self.plugin_path = plugin_path

    def argv(self) -> list[str]:
        from civex.plugins import subprocess_runtime as sr

        return sr._build_command(sr.find_uv_binary(), self.plugin_path)

    @property
    def key(self) -> Hashable:
        digest = hashlib.sha256(self.plugin_path.read_bytes()).hexdigest()
        return (digest, *self.argv())

    @property
    def label(self) -> str:
        return str(self.plugin_path)


# -- a container ---------------------------------------------------------------


class DockerLauncher(Launcher):
    """An image, run as one container per request (`docker run -i --rm
    <image> <mode>`): the container is the isolation boundary, so no
    sandboxing here, and a fresh one per request is what lets `--memory`/
    `--cpus` apply per run. A stuck one is stopped with `docker kill` by
    name, since killing the local client doesn't reliably stop it."""

    tier = PluginTier.CONTAINER
    reusable = False

    def __init__(
        self, image: str, memory: str | None = None, cpus: float | None = None
    ) -> None:
        self.image = image
        self.memory = memory
        self.cpus = cpus

    @property
    def key(self) -> Hashable:
        return ("docker", self.image, self.memory, self.cpus)

    @property
    def label(self) -> str:
        return self.image

    def start(self, mode: str) -> Connection:
        from civex.plugins import container_runtime as cr

        name = f"civex-plugin-{uuid.uuid4().hex}"
        argv = cr._build_command(
            cr.find_docker_binary(),
            self.image,
            mode,
            name,
            memory=self.memory,
            cpus=self.cpus,
        )
        scratch_dir = Path(tempfile.mkdtemp(prefix="civex-plugin-container-"))
        try:
            proc = cr._spawn(argv)
        except BaseException:
            shutil.rmtree(scratch_dir, ignore_errors=True)
            raise
        return ProcessConnection(
            proc, scratch_dir, kill=lambda: cr._kill_container(proc, name)
        )


# -- a thread in this process ----------------------------------------------------

_END = object()


class _Channel:
    """One direction of an in-memory frame stream: lines in a queue, ending
    when `end()` is called."""

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()

    def write(self, line: str) -> None:
        self._q.put(line)

    def end(self) -> None:
        self._q.put(_END)

    def lines(self) -> Iterator[str]:
        while True:
            line = self._q.get()
            if line is _END:
                return
            yield line


class InProcessConnection(Connection):
    """The SDK's `serve_loop` for a `Plugin` class, on a thread of its own,
    over two in-memory streams. Frames are still JSON text, so a built-in
    sees exactly what a plugin in a process would. It can't be stopped (a
    thread can't be killed): `stop()` only ends the host's side, and the
    thread finishes when it next asks the host for something or returns."""

    def __init__(self, plugin_cls: type[Plugin]) -> None:
        self.scratch_dir = None  # everything inline, as built-ins always were
        self._to_plugin = _Channel()
        self._to_host = _Channel()
        self.writer = FrameWriter(self._to_plugin.write)
        self.reader = FrameReader(self._to_host.lines())
        self._failure: BaseException | None = None
        self._thread = threading.Thread(
            target=self._serve,
            args=(plugin_cls,),
            name=f"civex-plugin-{plugin_cls.id}",
            daemon=True,
        )
        self._thread.start()

    def _serve(self, plugin_cls: type[Plugin]) -> None:
        try:
            serve_loop(
                plugin_cls,
                FrameReader(self._to_plugin.lines()),
                FrameWriter(self._to_host.write),
                scratch_dir=None,
            )
        except BaseException as e:  # noqa: BLE001 -- reported as death_message
            self._failure = e
        finally:
            self._to_host.end()

    def alive(self) -> bool:
        return self._thread.is_alive()

    def stop(self) -> None:
        self._to_plugin.end()
        self._to_host.end()

    def close(self) -> None:
        self._to_plugin.end()
        self._thread.join(timeout=2.0)

    def death_message(self) -> str:
        if self._failure is not None:
            return f"built-in plugin stopped: {self._failure!r}"
        return "built-in plugin stopped without a response"


class InProcessLauncher(Launcher):
    """A built-in: trusted code that ships with civex, run in this process
    through the same protocol, host functions and checks as any plugin. It
    isn't stopped by a step's timeout (a thread can't be killed), as
    built-ins never were."""

    tier = PluginTier.BUILTIN
    bounded = False

    def __init__(self, plugin_cls: type[Plugin]) -> None:
        self.plugin_cls = plugin_cls

    @property
    def key(self) -> Hashable:
        return ("builtin", self.plugin_cls.__module__, self.plugin_cls.__qualname__)

    @property
    def label(self) -> str:
        return self.plugin_cls.id

    def start(self, mode: str) -> Connection:
        return InProcessConnection(self.plugin_cls)
