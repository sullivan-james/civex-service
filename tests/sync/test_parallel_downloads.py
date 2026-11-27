"""Files come down several at a time, each still checked against its hash,
and what is stored is never lost to a later failure."""

from __future__ import annotations

import hashlib
import threading
import time

import pytest

from civex.domain.sync import SyncError


class Line:
    """A transport that serves files from a dict, as a network would: from
    any thread, a little slowly, counting how many are in hand at once."""

    download_threads = 4

    def __init__(self, files, *, wrong=(), fail=()):
        self.files, self.wrong, self.fail = files, set(wrong), set(fail)
        self.now = self.peak = 0
        self._lock = threading.Lock()
        self.asked: list[str] = []

    def file_chunks(self, sha):
        with self._lock:
            self.asked.append(sha)
            self.now += 1
            self.peak = max(self.peak, self.now)
        try:
            time.sleep(0.02)
            if sha in self.fail:
                raise SyncError("the line dropped")
            if sha not in self.files:
                raise FileNotFoundError(sha)
            data = self.files[sha]
            if sha in self.wrong:
                data = b"not it" + data
            return iter([data[:5], data[5:]])
        finally:
            with self._lock:
                self.now -= 1

    def close(self):
        pass


def _cite(laptop, record, contents):
    laptop.schema_svc.add_field("encounter", "scan", "file")
    laptop.commit()
    files = {}
    for i, content in enumerate(contents):
        ref = laptop.file_svc.store_bytes(content, f"s{i}.bin")
        rec = laptop.record_svc.add("study", "encounter", {"site": f"s{i}"})
        laptop.record_svc.update(str(rec.id), {"site": f"s{i}", "scan": ref.to_dict()})
        files[ref.sha256] = content
    laptop.commit()
    laptop.sync_svc.sync()
    return files


def _phone(pair, monkeypatch, line_for):
    laptop, phone, record = pair
    files = _cite(laptop, record, [f"file number {i} ".encode() * 9 for i in range(30)])
    phone.sync_svc.sync()
    line = line_for(files)
    svc = object.__getattribute__(phone.sync_svc, "_svc")
    monkeypatch.setattr(svc, "_transport", lambda: line)
    return phone, files, line


def test_several_files_come_at_once_and_each_is_stored(pair, monkeypatch):
    phone, files, line = _phone(pair, monkeypatch, Line)
    told: list[int] = []

    report = phone.sync_svc.fetch_files(progress=told.append)
    phone.commit()

    assert report.fetched == 30 and not report.absent
    assert told == list(range(1, 31))
    assert line.peak > 1
    for sha, content in files.items():
        assert phone.file_svc.retrieve(sha) == content
    assert phone.sync_svc.files_missing() == 0


def test_a_file_with_the_wrong_content_is_refused_and_the_rest_stays(pair, monkeypatch):
    seen = {}

    def make(files):
        seen["bad"] = sorted(files)[20]
        return Line(files, wrong=[seen["bad"]])

    phone, files, line = _phone(pair, monkeypatch, make)

    with pytest.raises(SyncError, match="wrong content"):
        phone.sync_svc.fetch_files()
    phone.commit()

    assert not phone.file_svc.exists(seen["bad"])
    # Files in hash order before it were stored and confirmed, not lost.
    before = sorted(files)[:20]
    assert all(phone.file_svc.exists(s) for s in before)
    assert phone.sync_svc.not_on_server(set(before)) == set()


def test_a_line_that_drops_loses_nothing_already_stored(pair, monkeypatch):
    seen = {}

    def make(files):
        seen["bad"] = sorted(files)[15]
        return Line(files, fail=[seen["bad"]])

    phone, files, line = _phone(pair, monkeypatch, make)

    with pytest.raises(SyncError, match="dropped"):
        phone.sync_svc.fetch_files()
    phone.commit()
    before = sorted(files)[:15]
    assert all(phone.file_svc.exists(s) for s in before)

    line.fail.clear()  # the next pass takes up where it stopped
    report = phone.sync_svc.fetch_files()
    phone.commit()
    assert report.fetched >= 1
    assert all(phone.file_svc.exists(s) for s in files)


def test_files_the_server_lacks_are_noted_and_the_others_come(pair, monkeypatch):
    seen = {}

    def make(files):
        gone = sorted(files)[3:6]
        seen["gone"] = gone
        return Line({s: c for s, c in files.items() if s not in gone})

    phone, files, line = _phone(pair, monkeypatch, make)

    report = phone.sync_svc.fetch_files()
    phone.commit()

    assert sorted(report.absent) == sorted(seen["gone"])
    assert report.fetched == 27
    assert phone.sync_repo.server_lacks_of(set(seen["gone"])) == set(seen["gone"])


def test_limit_stops_after_that_many_and_keeps_what_is_in_hand(pair, monkeypatch):
    phone, files, line = _phone(pair, monkeypatch, Line)

    report = phone.sync_svc.fetch_files(limit=7)
    phone.commit()

    assert report.stopped and report.attempted == 7 and report.fetched == 7
    assert sum(phone.file_svc.exists(s) for s in files) == 7
    assert len(line.asked) == 7


def test_seconds_stops_the_pass(pair, monkeypatch):
    phone, files, line = _phone(pair, monkeypatch, Line)

    report = phone.sync_svc.fetch_files(seconds=0.0)

    assert report.stopped and report.attempted == 0


def test_skip_is_not_asked_for(pair, monkeypatch):
    phone, files, line = _phone(pair, monkeypatch, Line)
    skipped = set(sorted(files)[:4])

    report = phone.sync_svc.fetch_files(skip=skipped)

    assert report.fetched == 26 and not (skipped & set(line.asked))


def test_the_hash_of_a_file_is_what_was_asked_for(pair, monkeypatch):
    phone, files, line = _phone(pair, monkeypatch, Line)
    phone.sync_svc.fetch_files()
    for sha in files:
        assert hashlib.sha256(phone.file_svc.retrieve(sha)).hexdigest() == sha
