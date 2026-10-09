"""One machine at a time may serve a project over SSH (`civex/project_host.py`):
a home folder shared by every lab machine must not have its database written
by two at once."""

from __future__ import annotations

import json
import os
import time

import pytest

from civex.project_host import FILE, STALE, HostLock, OpenElsewhere


def test_the_same_machine_may_open_it_again(tmp_path):
    first, second = HostLock(tmp_path, "lab-03"), HostLock(tmp_path, "lab-03")
    first.acquire()
    second.acquire()
    first.release()
    second.release()


def test_another_machine_is_refused_while_it_is_in_use(tmp_path):
    held = HostLock(tmp_path, "lab-03")
    held.acquire()
    with pytest.raises(OpenElsewhere, match="open on lab-03"):
        HostLock(tmp_path, "lab-07").acquire()
    held.release()


def test_a_machine_that_stopped_using_it_is_taken_over(tmp_path):
    HostLock(tmp_path, "lab-03").acquire()
    old = time.time() - STALE - 1
    os.utime(tmp_path / FILE, (old, old))
    later = HostLock(tmp_path, "lab-07")
    later.acquire()
    assert json.loads((tmp_path / FILE).read_text())["host"] == "lab-07"
    later.release()
