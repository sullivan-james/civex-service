"""Sync to a project on another machine reached by SSH (`ssh://`): a real
`civex sync ssh-serve` process at the far end, reached through SSH's port
forwarding, with `tests/sync/fake_ssh.py` standing in for ssh."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from civex.config import load_config, save_config
from civex.domain.sync import SyncError
from civex.project_host import FILE
from civex.services import ssh_tunnel
from civex.services.ssh_tunnel import SshAddress

from .peers import snapshots
from .test_convergence import populate

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the far end of ssh:// is a Unix machine"
)


@pytest.fixture()
def lab(project, tmp_path: Path, monkeypatch) -> Iterator[tuple[str, str, object]]:
    """An authority on "the lab machine", its address, and an invite."""
    authority = project("lab")
    root = tmp_path / "lab"
    previous = os.getcwd()
    os.chdir(root)
    try:
        config = load_config()
        config.sync.serve = True
        save_config(config)
    finally:
        os.chdir(previous)
    _, invite = authority.device_keys.invite("laptop")
    authority.commit()

    venv_bin = Path(sys.executable).parent
    monkeypatch.setenv(
        "CIVEX_SSH_COMMAND",
        f"{sys.executable} {Path(__file__).with_name('fake_ssh.py')}",
    )
    monkeypatch.setenv("PATH", f"{venv_bin}{os.pathsep}{os.environ['PATH']}")
    try:
        yield f"ssh://me@lab{root}", invite, authority
    finally:
        ssh_tunnel.close_all()


def test_a_project_is_cloned_and_synced_over_ssh(project, lab):
    url, invite, authority = lab
    first = project("first")
    populate(first)
    assert first.sync_svc.connect(url, invite) == "seeded"
    first.commit()
    assert len(snapshots(authority)["record"]) == 4

    _, invite2 = authority.device_keys.invite("tablet")
    authority.commit()
    second = project("second")
    assert second.sync_svc.connect(url, invite2) == "joined"
    second.commit()
    assert snapshots(second)["record"] == snapshots(authority)["record"]


def test_files_travel_both_ways_over_ssh(project, lab):
    url, invite, authority = lab
    laptop = project("laptop")
    populate(laptop)
    laptop.schema_svc.add_field("encounter", "scan", "file")
    laptop.sync_svc.connect(url, invite)
    laptop.commit()
    record = laptop.record_svc.find("study", "encounter", limit=1)[0]
    content = os.urandom(3 * 1024 * 1024)
    ref = laptop.file_svc.store_bytes(content, "scan.bin")
    laptop.record_svc.update(
        str(record.id), {"site": "x", "depth": 1.0, "scan": ref.to_dict()}
    )
    laptop.commit()
    laptop.sync_svc.sync()
    assert authority.file_svc.retrieve(ref.sha256) == content

    _, invite2 = authority.device_keys.invite("tablet")
    authority.commit()
    tablet = project("tablet")
    tablet.sync_svc.connect(url, invite2)
    tablet.commit()
    tablet.sync_svc.fetch_files()
    tablet.commit()
    assert tablet.file_svc.retrieve(ref.sha256) == content


def test_one_tunnel_serves_every_call(project, lab):
    url, invite, _ = lab
    laptop = project("laptop")
    laptop.sync_svc.connect(url, invite)
    laptop.commit()
    first = ssh_tunnel.local_url(url)
    laptop.sync_svc.sync()
    assert ssh_tunnel.local_url(url) == first


def test_a_project_open_on_another_machine_is_refused_for_now(project, lab, tmp_path):
    url, invite, _ = lab
    (tmp_path / "lab" / "_civex" / FILE).write_text('{"host": "lab-07"}')
    laptop = project("laptop")
    with pytest.raises(SyncError, match="open on lab-07") as e:
        laptop.sync_svc.connect(url, invite)
    assert e.value.retryable


def test_a_folder_that_is_not_a_project_is_said_plainly(project, lab, tmp_path):
    _, invite, _ = lab
    laptop = project("laptop")
    with pytest.raises(SyncError, match="not a civex project") as e:
        laptop.sync_svc.connect(f"ssh://me@lab{tmp_path}/nothing", invite)
    assert not e.value.retryable


def test_ssh_refusing_to_sign_in_is_not_retried(project, lab, monkeypatch):
    url, invite, _ = lab
    monkeypatch.setenv("FAKE_SSH_FAIL", "me@lab: Permission denied (publickey).")
    laptop = project("laptop")
    with pytest.raises(SyncError, match="SSH key") as e:
        laptop.sync_svc.connect(url, invite)
    assert not e.value.retryable


@pytest.mark.parametrize(
    ("url", "host", "port", "path", "civex"),
    [
        ("ssh://lab/srv/birds", "lab", None, "/srv/birds", None),
        ("ssh://me@lab:2222/~/birds", "me@lab", 2222, "~/birds", None),
        (
            "ssh://lab/~/my%20birds?civex=/opt/civex/bin/civex",
            "lab",
            None,
            "~/my birds",
            "/opt/civex/bin/civex",
        ),
    ],
)
def test_ssh_addresses_are_read(url, host, port, path, civex):
    assert SshAddress.parse(url) == SshAddress(host, port, path, civex)


@pytest.mark.parametrize("url", ["ssh://lab", "ssh://lab/", "ssh:///srv/birds"])
def test_an_ssh_address_without_a_host_or_path_is_refused(url):
    with pytest.raises(SyncError, match="ssh://"):
        SshAddress.parse(url)


def test_a_civex_too_old_at_the_far_end_is_named(project, lab, tmp_path):
    """An older civex answers with a framed CLI error; what reaches the person
    says what to do, not the frame's bottom border."""
    url, invite, _ = lab
    old = tmp_path / "old-civex"
    old.write_text(
        "#!/bin/sh\n"
        'echo "╭─ Error ──╮" >&2\n'
        "echo \"│ No such command 'ssh-serve'. │\" >&2\n"
        'echo "╰──────────╯" >&2\n'
        "exit 2\n"
    )
    old.chmod(0o755)
    laptop = project("laptop")
    with pytest.raises(SyncError, match="too old") as e:
        laptop.sync_svc.connect(f"{url}?civex={old}", invite)
    assert not e.value.retryable
