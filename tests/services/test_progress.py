"""How far a long request has got, for a client waiting on it."""

from __future__ import annotations

import threading

import pytest

from civex.services import progress as progress_module
from civex.services.progress import ProgressRegistry


def test_ids_are_short_and_plain() -> None:
    valid = ProgressRegistry.valid

    assert valid("3f2b8c1e-9d4a-4e1f-8a7b-1c2d3e4f5a6b")
    assert valid("abcdefgh")
    assert not valid(None) and not valid("") and not valid("short")
    assert not valid("a" * 65)
    assert not valid("has spaces in it")
    assert not valid("../../etc/passwd")


def test_work_reports_a_stage_and_how_far_it_has_got() -> None:
    registry = ProgressRegistry()
    progress = registry.start("abcdefgh")

    progress.phase("Finding files", 1000)
    progress.advance(250)

    assert registry.get("abcdefgh") == {
        "phase": "Finding files",
        "done": 250,
        "total": 1000,
        "finished": False,
        "error": None,
        "bytes_done": 0,
        "bytes_total": 0,
        "rate": 0.0,
        "eta": None,
    }


def test_a_new_stage_starts_again_from_nothing() -> None:
    registry = ProgressRegistry()
    progress = registry.start("abcdefgh")
    progress.phase("Finding files", 10)
    progress.advance(10)

    progress.phase("Making the folder", 4)

    state = registry.get("abcdefgh")
    assert (state["phase"], state["done"], state["total"]) == (
        "Making the folder",
        0,
        4,
    )


def test_a_total_that_becomes_known_later_can_be_given_with_the_count() -> None:
    registry = ProgressRegistry()
    progress = registry.start("abcdefgh")
    progress.phase("Finding what is inside")

    assert registry.get("abcdefgh")["total"] == 0  # not known yet
    progress.advance(40, total=200)

    state = registry.get("abcdefgh")
    assert (state["done"], state["total"]) == (40, 200)


def test_it_says_when_the_work_has_finished_and_how() -> None:
    registry = ProgressRegistry()
    ok = registry.start("okokokok")
    bad = registry.start("badbadba")

    ok.finish()
    bad.finish("the drive went")

    assert registry.get("okokokok")["finished"] is True
    assert registry.get("okokokok")["error"] is None
    assert registry.get("badbadba")["error"] == "the drive went"


def test_an_unknown_id_is_nothing() -> None:
    assert ProgressRegistry().get("never-seen") is None


def test_a_finished_request_is_forgotten_after_a_while_and_a_running_one_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1000.0]
    monkeypatch.setattr(progress_module.time, "monotonic", lambda: now[0])
    registry = ProgressRegistry()
    done = registry.start("finished1")
    done.finish()
    registry.start("running01")

    now[0] += progress_module._KEEP_FINISHED_SECONDS + 1
    registry.start("another01")  # starting one tidies up

    assert registry.get("finished1") is None
    assert registry.get("running01") is not None


def test_one_that_was_never_finished_is_forgotten_eventually(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    monkeypatch.setattr(progress_module.time, "monotonic", lambda: now[0])
    registry = ProgressRegistry()
    registry.start("abandoned")

    now[0] += progress_module._KEEP_UNTOUCHED_SECONDS + 1
    registry.start("another01")

    assert registry.get("abandoned") is None


def test_reporting_from_several_threads_is_safe() -> None:
    registry = ProgressRegistry()
    progress = registry.start("threaded1")
    progress.phase("work", 4000)

    def work() -> None:
        for i in range(1000):
            progress.advance(i)
            registry.get("threaded1")

    threads = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    state = registry.get("threaded1")
    assert state["total"] == 4000 and 0 <= state["done"] < 1000


def test_a_stage_that_moves_bytes_says_how_many_how_fast_and_how_long() -> None:
    registry = ProgressRegistry()
    progress = registry.start("bytesbytes")
    progress.phase("Downloading 2 files from the server", 2, total_bytes=1000)
    progress.add_bytes(200)
    state = registry.get("bytesbytes")
    assert (state["bytes_done"], state["bytes_total"]) == (200, 1000)
    # A new stage starts its own count.
    progress.phase("Writing tables", 3)
    assert registry.get("bytesbytes")["bytes_done"] == 0
