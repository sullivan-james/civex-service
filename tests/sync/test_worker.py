"""When a project syncs by itself: after edits, on an interval, on request; and
how it backs off when the authority can't be reached."""

from __future__ import annotations

from types import SimpleNamespace

from civex.config import SyncConfig
from civex.domain.sync import SyncError
from civex.services.sync_lock import SyncBusy
from civex.services.sync_worker import BASE_BACKOFF, DEBOUNCE, MAX_BACKOFF, SyncWorker


class Rig:
    def __init__(self) -> None:
        self.now = 1000.0
        self.pending = 0
        self.outcomes: list[object] = []  # exceptions raise; anything else returns
        self.calls = 0
        self.to_fetch = 0
        self.fetches: list[dict] = []
        self.fail_fetch: Exception | None = None
        self.sync_config = SyncConfig(remote="http://a", interval_seconds=60)
        self.worker = SyncWorker(self._config, self._ctx, clock=lambda: self.now)

    def _config(self):
        return SimpleNamespace(sync=self.sync_config)

    def _ctx(self, _config):
        def sync(check_files=True):
            self.calls += 1
            out = self.outcomes.pop(0) if self.outcomes else "report"
            if isinstance(out, Exception):
                raise out
            return out

        def fetch_files(**kw):
            self.fetches.append(kw)
            if self.fail_fetch:
                raise self.fail_fetch
            done = self.to_fetch
            if kw.get("progress") and done:
                kw["progress"](done)
            self.to_fetch = 0
            return SimpleNamespace(absent=[], stopped=False, fetched=done)

        return SimpleNamespace(
            sync_repo=SimpleNamespace(
                count_pending=lambda: self.pending,
                meta=lambda: SimpleNamespace(history_from=None),
            ),
            sync_svc=SimpleNamespace(
                sync=sync,
                files_to_fetch=lambda: self.to_fetch,
                fetch_files=fetch_files,
            ),
            close=lambda: None,
        )

    def tick(self, advance: float = 0.0):
        self.now += advance
        return self.worker.tick()


def test_it_syncs_at_once_then_waits_for_the_interval() -> None:
    r = Rig()
    assert r.tick() == "report"
    assert r.tick(10) is None
    assert r.tick(60) == "report"
    assert r.calls == 2


def test_it_does_nothing_without_an_authority_or_when_paused() -> None:
    r = Rig()
    r.sync_config.remote = None
    assert r.tick() is None
    r.sync_config.remote = "http://a"
    r.sync_config.paused = True
    assert r.tick(1000) is None and r.calls == 0  # the schedule stops
    r.worker.request()
    assert r.tick() == "report"  # but asking still works
    assert r.tick(1000) is None and r.calls == 1


def test_local_changes_go_after_a_short_pause_not_at_every_tick() -> None:
    r = Rig()
    r.tick()
    r.pending = 3
    assert r.tick(1) is None  # within the debounce of the last attempt
    assert r.tick(DEBOUNCE) == "report"


def test_a_request_syncs_now_whatever_the_schedule() -> None:
    r = Rig()
    r.tick()
    r.worker.request()
    assert r.tick(1) == "report"


def test_a_failure_backs_off_and_a_success_resets_it() -> None:
    r = Rig()
    r.outcomes = [SyncError("down"), SyncError("down")]
    assert r.tick() is None
    r.pending = 1
    assert r.tick(BASE_BACKOFF) is None  # still backing off (waits 10s after 1st)
    assert r.calls == 1
    assert r.tick(BASE_BACKOFF * 2) is None  # second failure
    assert r.calls == 2
    assert r.tick(1) is None and r.calls == 2  # 20s back-off now
    assert r.tick(BASE_BACKOFF * 4) == "report"
    assert r.worker._failures == 0


def test_a_refusal_waits_the_longest() -> None:
    r = Rig()
    r.outcomes = [SyncError("revoked", retryable=False, status=401)]
    r.tick()
    r.pending = 1
    assert r.tick(MAX_BACKOFF - 1) is None
    assert r.tick(2) == "report"


def test_a_busy_project_is_left_alone() -> None:
    r = Rig()
    r.outcomes = [SyncBusy()]
    assert r.tick() is None
    assert r.worker._failures == 0


def test_never_syncs_only_when_asked() -> None:
    r = Rig()
    r.sync_config.interval_seconds = 0
    r.pending = 5
    assert r.tick(1000) is None and r.calls == 0  # not by schedule, not for edits
    r.worker.request()
    assert r.tick() == "report"
    assert r.tick(1000) is None and r.calls == 1


def test_files_kept_here_are_downloaded_in_the_background_and_nothing_else():
    r = Rig()
    r.to_fetch = 3  # what the collections kept here still lack
    r.tick()
    assert len(r.fetches) == 1 and r.to_fetch == 0
    r.tick(1000)  # nothing left to fetch (none kept, or all here): no call
    assert len(r.fetches) == 1


def test_asking_for_downloads_shows_progress_at_once_and_runs_before_any_sync():
    seen: list = []
    r = Rig()
    r.worker._on_progress = seen.append
    r.to_fetch = 4
    r.worker.request_files(4)
    # Shown the moment it is asked for, before the worker has done anything.
    assert seen and (seen[0].phase, seen[0].done, seen[0].total) == ("files", 0, 4)

    r.worker._backoff_until = r.now + 500  # an earlier sync failed
    r.sync_config.paused = True
    r.tick()
    assert len(r.fetches) == 1  # asked for: not held by the back-off or a pause
    assert r.calls == 0  # and no sync was needed first
    assert seen[-1] is None  # all here: the bar goes


def test_a_download_that_cannot_reach_the_server_does_not_leave_a_bar():
    from civex.domain.sync import SyncError

    seen: list = []
    r = Rig()
    r.worker._on_progress = seen.append
    r.to_fetch = 2
    r.fail_fetch = SyncError("no server")
    r.worker.request_files(2)
    r.tick()
    assert seen[-1] is None
