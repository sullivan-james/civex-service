"""The one client transport: its status table, keep-alive connections, gzip
negotiation and push batching, against a plain local HTTP server."""

from __future__ import annotations

import gzip
import json
import random
import threading
import uuid
from collections.abc import Iterator
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from civex.domain.sync import SyncEntry, SyncError
from civex.services import http_wire
from civex.services.http_wire import Wire, parse_retry_after, retry_wait, status_error
from civex.domain.sync import batch_by_budget
from civex.services.sync_transport import (
    CLIENT_PUSH_TIMEOUT_SECONDS,
    HttpSyncTransport,
)


class _Server:
    """Answers from a script: `plan` is a list of (status, headers, body) taken
    in order (the last repeats); records what it saw."""

    def __init__(self) -> None:
        self.plan: list[tuple[int, dict[str, str], bytes]] = [(200, {}, b"{}")]
        self.seen: list[dict[str, Any]] = []
        self.peers: set[tuple[str, int]] = set()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _go(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                outer.peers.add(self.client_address)
                outer.seen.append(
                    {"path": self.path, "headers": dict(self.headers), "body": raw}
                )
                n = len(outer.seen) - 1
                status, headers, body = outer.plan[min(n, len(outer.plan) - 1)]
                if self.headers.get("Accept-Encoding") == "gzip" and status < 300:
                    body = gzip.compress(body)
                    headers = {**headers, "Content-Encoding": "gzip"}
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = do_PUT = _go  # noqa: N815

            def log_message(self, *args: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def server() -> Iterator[_Server]:
    s = _Server()
    try:
        yield s
    finally:
        s.close()


def _wire(sleeps: list[float]) -> Wire:
    return Wire(sleep=sleeps.append, rng=random.Random(1))


# -- the status table ----------------------------------------------------


def test_retry_after_is_seconds_or_a_date() -> None:
    assert parse_retry_after("7") == 7.0
    assert parse_retry_after(" 2.5 ") == 2.5
    assert parse_retry_after("-3") == 0.0
    assert parse_retry_after("soon") is None
    assert parse_retry_after(None) is None
    when = datetime.now(timezone.utc) + timedelta(seconds=30)
    got = parse_retry_after(format_datetime(when, usegmt=True))
    assert got is not None and 25 <= got <= 31
    past = datetime.now(timezone.utc) - timedelta(seconds=30)
    assert parse_retry_after(format_datetime(past, usegmt=True)) == 0.0


def test_the_wait_is_capped_and_jittered_within_25_percent() -> None:
    rng = random.Random(7)
    for _ in range(200):
        assert 3.75 <= retry_wait(5.0, 0, rng) <= 6.25
        capped = retry_wait(10_000.0, 0, rng)
        assert 0.75 * http_wire.RETRY_AFTER_CAP_SECONDS <= capped
        assert capped <= 1.25 * http_wire.RETRY_AFTER_CAP_SECONDS
    # No Retry-After: exponential, still jittered, capped
    assert 0.375 <= retry_wait(None, 0, rng) <= 0.625
    assert retry_wait(None, 30, rng) <= 1.25 * http_wire.BACKOFF_CAP_SECONDS


def test_429_waits_retry_after_and_sends_the_same_request_again(server) -> None:
    server.plan = [
        (429, {"Retry-After": "2"}, b'{"detail": "slow down"}'),
        (503, {"Retry-After": "1"}, b""),
        (200, {}, b'{"ok": true}'),
    ]
    sleeps: list[float] = []
    reply = _wire(sleeps).request("POST", server.url + "/x", body=b"abc")
    assert reply.json() == {"ok": True}
    assert [s["body"] for s in server.seen] == [b"abc"] * 3
    assert len(sleeps) == 2
    assert 1.5 <= sleeps[0] <= 2.5 and 0.75 <= sleeps[1] <= 1.25


def test_a_server_that_keeps_saying_429_ends_the_call_retryably(server) -> None:
    server.plan = [(429, {"Retry-After": "3"}, b"")]
    sleeps: list[float] = []
    with pytest.raises(SyncError) as raised:
        _wire(sleeps).request("GET", server.url + "/x")
    assert raised.value.retryable and raised.value.status == 429
    assert raised.value.retry_after == 3.0  # for the worker to wait on
    assert len(sleeps) == http_wire.MAX_STATUS_RETRIES


def test_5xx_backs_off_with_jitter_and_501_does_not_retry(server) -> None:
    server.plan = [(502, {}, b""), (500, {}, b""), (200, {}, b"{}")]
    sleeps: list[float] = []
    _wire(sleeps).request("GET", server.url + "/x")
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0] * 0.9
    server.seen.clear()
    server.plan = [(501, {}, b'{"detail": "no"}')]
    with pytest.raises(SyncError) as raised:
        _wire([]).request("GET", server.url + "/x")
    assert not raised.value.retryable and len(server.seen) == 1


@pytest.mark.parametrize(
    "status,body,words",
    [
        (413, b'{"detail": {"code": "too_large"}}', "too big to send in one go"),
        (413, b"<html>", "too big to send in one go"),
        (402, b'{"detail": "over the plan"}', "over the plan"),
    ],
)
def test_413_and_402_are_not_retried_and_say_why(server, status, body, words) -> None:
    server.plan = [(status, {}, body)]
    sleeps: list[float] = []
    with pytest.raises(SyncError) as raised:
        _wire(sleeps).request("POST", server.url + "/x", body=b"x")
    assert not raised.value.retryable and raised.value.status == status
    assert words in str(raised.value)
    assert len(server.seen) == 1 and sleeps == []


def test_a_network_error_backs_off_then_gives_up() -> None:
    sleeps: list[float] = []
    with pytest.raises(SyncError) as raised:
        _wire(sleeps).request("GET", "http://127.0.0.1:1/x")
    assert raised.value.retryable
    assert len(sleeps) == http_wire.MAX_NETWORK_RETRIES


def test_status_table_marks() -> None:
    def reply(status: int) -> http_wire.Reply:
        return http_wire.Reply(status, http_wire.Message(), b"")

    assert status_error(reply(401)).retryable is False
    assert status_error(reply(404)).retryable is False
    assert status_error(reply(500)).retryable is True
    assert status_error(reply(422)).retryable is False


# -- connections ----------------------------------------------------------


def test_n_calls_share_one_connection(server) -> None:
    wire = Wire()
    for _ in range(8):
        wire.request("GET", server.url + "/x")
    assert len(server.peers) == 1
    assert wire.connections_made == 1
    wire.close()


def test_each_thread_has_its_own_connection_and_reuses_it(server) -> None:
    wire = Wire()

    def work() -> None:
        for _ in range(5):
            wire.request("GET", server.url + "/x")

    threads = [threading.Thread(target=work) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert 1 <= wire.connections_made <= 3  # idle ones are shared
    assert wire.open_connections() <= 3
    wire.close()


def test_a_connection_the_server_closed_is_replaced_silently(server) -> None:
    wire = Wire()
    wire.request("GET", server.url + "/x")
    for conn in list(wire._all):  # the server (or a proxy) dropped it
        conn.sock.close()
    wire.request("GET", server.url + "/x")
    assert wire.connections_made == 2
    wire.close()


def test_a_redirect_is_not_followed_to_another_host_with_the_token(server) -> None:
    server.plan = [(307, {"Location": "http://127.0.0.2:1/elsewhere"}, b"")]
    with pytest.raises(SyncError) as raised:
        Wire().request(
            "GET",
            server.url + "/x",
            headers={"Authorization": "Bearer secret"},
            follow="same_host",
        )
    assert not raised.value.retryable
    assert len(server.seen) == 1


# -- gzip -----------------------------------------------------------------


def _hello(caps: list[str]) -> bytes:
    return json.dumps(
        {
            "protocol_version": 6,
            "project_id": str(uuid.uuid4()),
            "head_seq": 0,
            "empty": True,
            "capabilities": caps,
        }
    ).encode()


def _transport(server: _Server) -> HttpSyncTransport:
    from civex.domain.sync import DeviceCredentials, SessionGrant

    t = HttpSyncTransport(server.url, DeviceCredentials("d", "k", "a"))
    t._session = SessionGrant(token="t", expires_at=9_000_000_000, signature="s")
    return t


def _entries(n: int, width: int = 3000) -> list[SyncEntry]:
    return [
        SyncEntry(
            id=uuid.uuid4(),
            action="create",
            entity_type="record",
            entity_id=uuid.uuid4(),
            old_data=None,
            new_data={"v": "x" * width},
            timestamp="2026-01-01T00:00:00+00:00",
        )
        for _ in range(n)
    ]


def _push_with(server: _Server, caps: list[str]) -> dict[str, Any]:
    server.plan = [
        (200, {}, _hello(caps)),
        (200, {}, json.dumps({"results": [], "head_seq": 0}).encode()),
    ]
    t = _transport(server)
    t.push(_entries(3))
    assert server.seen[0]["path"].endswith("/hello")
    assert server.seen[0]["headers"].get("Accept-Encoding") == "gzip"
    return server.seen[1]


def test_push_body_is_gzipped_only_when_the_server_says_it_reads_it(server) -> None:
    sent = _push_with(server, ["gzip_requests"])
    assert sent["headers"].get("Content-Encoding") == "gzip"
    assert len(json.loads(gzip.decompress(sent["body"]))["entries"]) == 3
    assert int(sent["headers"]["Content-Length"]) == len(sent["body"])


def test_push_body_is_plain_for_a_server_without_the_capability(server) -> None:
    server.seen.clear()
    sent = _push_with(server, [])
    assert "Content-Encoding" not in sent["headers"]
    assert len(json.loads(sent["body"])["entries"]) == 3


def test_a_server_that_answers_plain_json_still_works(server) -> None:
    server.plan = [(200, {}, b'{"a": 1}')]
    wire = Wire()
    # (the test server gzips only when asked; ask not to)
    reply = wire.request("GET", server.url + "/x", accept_gzip=False)
    assert reply.json() == {"a": 1}


def test_timeouts_are_set_per_call_type() -> None:
    assert CLIENT_PUSH_TIMEOUT_SECONDS == 120.0


# -- push batching ----------------------------------------------------------


def _sized(entry: SyncEntry) -> int:
    return len(entry.new_data["v"])  # type: ignore[index]


def test_batches_stop_at_the_byte_budget() -> None:
    entries = _entries(10, width=1000)
    taken = batch_by_budget(entries, 250, 3500, size_of=_sized)
    assert taken == entries[:3]


def test_batches_stop_at_the_entry_limit() -> None:
    entries = _entries(10, width=10)
    assert batch_by_budget(entries, 4, 10**9, size_of=_sized) == entries[:4]


def test_an_action_is_never_split_and_an_oversize_one_goes_alone() -> None:
    entries = _entries(6, width=1000)
    op = "a1"
    for e in entries[1:4]:
        e.op = op  # one action of three entries (3000 bytes)
    # 1000 + 3000 > 3500: the action doesn't fit after the first entry
    assert batch_by_budget(entries, 250, 3500, size_of=_sized) == entries[:1]
    # An action over the budget goes alone, whole
    solo = batch_by_budget(entries[1:], 250, 500, size_of=_sized)
    assert solo == entries[1:4]
    # and the first action is always taken, even above the entry limit
    assert batch_by_budget(entries[1:], 1, 10**9, size_of=_sized) == entries[1:4]


def test_default_budget_is_about_2_mib_of_serialized_entries() -> None:
    entries = _entries(1000, width=20000)
    taken = batch_by_budget(entries, 250)
    total = sum(len(json.dumps(e.to_dict())) for e in taken)
    assert 100 < len(taken) < 250
    assert total <= 2 * 1024 * 1024 + 4000


# -- idempotence --------------------------------------------------------------


def test_a_post_is_not_sent_again_after_a_5xx_or_a_timeout(server) -> None:
    server.plan = [(504, {}, b"")]
    sleeps: list[float] = []
    with pytest.raises(SyncError):
        _wire(sleeps).request("POST", server.url + "/x", body=b"{}")
    assert len(server.seen) == 1 and sleeps == []


def test_a_post_is_sent_again_on_429_and_503_and_an_idempotent_one_on_504(
    server,
) -> None:
    server.plan = [(503, {"Retry-After": "1"}, b""), (200, {}, b"{}")]
    _wire([]).request("POST", server.url + "/x", body=b"{}")
    assert len(server.seen) == 2
    server.seen.clear()
    server.plan = [(504, {}, b""), (200, {}, b"{}")]
    _wire([]).request("POST", server.url + "/x", body=b"{}", idempotent=True)
    assert len(server.seen) == 2


def test_a_post_that_went_out_and_got_no_answer_is_not_resent() -> None:
    import socket

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = listener.getsockname()[1]
    got: list[bytes] = []

    def serve() -> None:
        while True:
            try:
                c, _ = listener.accept()
            except OSError:
                return
            got.append(c.recv(65536))
            c.close()  # no answer at all

    threading.Thread(target=serve, daemon=True).start()
    sleeps: list[float] = []
    with pytest.raises(SyncError) as raised:
        _wire(sleeps).request("POST", f"http://127.0.0.1:{port}/x", body=b"{}")
    assert len(got) == 1 and sleeps == []
    assert "may have done it" in str(raised.value)
    got.clear()
    with pytest.raises(SyncError):  # a GET is sent again, with back-off
        _wire(sleeps).request("GET", f"http://127.0.0.1:{port}/x")
    assert len(got) > 1
    listener.close()


# -- proxies --------------------------------------------------------------------


def test_plain_http_goes_to_the_proxy_with_the_whole_address(
    server, monkeypatch
) -> None:
    server.plan = [(200, {}, b'{"via": "proxy"}')]
    monkeypatch.setattr(
        "urllib.request.getproxies", lambda: {"http": server.url.replace("http://", "")}
    )
    monkeypatch.setattr("urllib.request.proxy_bypass", lambda host: False)
    reply = Wire().request("GET", "http://authority.example:8123/api/x?a=1")
    assert reply.json() == {"via": "proxy"}
    assert server.seen[0]["path"] == "http://authority.example:8123/api/x?a=1"


def test_https_is_tunnelled_through_the_proxy_with_connect(monkeypatch) -> None:
    import socket

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = listener.getsockname()[1]
    lines: list[str] = []

    def serve() -> None:
        c, _ = listener.accept()
        lines.append(c.recv(65536).decode("latin-1"))
        c.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        c.close()

    threading.Thread(target=serve, daemon=True).start()
    monkeypatch.setattr(
        "urllib.request.getproxies",
        lambda: {"https": f"http://user:pw@127.0.0.1:{port}"},
    )
    monkeypatch.setattr("urllib.request.proxy_bypass", lambda host: False)
    with pytest.raises(SyncError):
        Wire(sleep=lambda s: None).request(
            "GET", "https://hub.example.com/x", timeout=1.0
        )
    assert lines[0].startswith("CONNECT hub.example.com:443 HTTP/1.1")
    assert "Proxy-Authorization: Basic " in lines[0]
    listener.close()


def test_no_proxy_is_honoured(server, monkeypatch) -> None:
    monkeypatch.setattr("urllib.request.getproxies", lambda: {"http": "127.0.0.1:1"})
    monkeypatch.setattr("urllib.request.proxy_bypass", lambda host: True)
    assert Wire().request("GET", server.url + "/x").status == 200


# -- no sockets left behind -------------------------------------------------------


def test_many_threads_and_streams_leave_no_open_sockets(server) -> None:
    wire = Wire()

    def one() -> None:
        wire.request("PUT", server.url + "/part", body=b"x" * 100)

    for _ in range(30):  # thirty "big files", each with its own four threads
        threads = [threading.Thread(target=one) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert wire.open_connections() <= http_wire.MAX_IDLE_PER_HOST
    for _ in range(20):  # streamed downloads give theirs back
        with wire.request("GET", server.url + "/f", stream=True) as r:
            r.read()
    assert wire.open_connections() <= http_wire.MAX_IDLE_PER_HOST
    for _ in range(20):  # an abandoned stream is closed, not kept
        wire.request("GET", server.url + "/f", stream=True).close()
    assert wire.open_connections() <= http_wire.MAX_IDLE_PER_HOST
    wire.close()
    assert wire.open_connections() == 0


def test_a_transport_closes_its_connections(server) -> None:
    t = _transport(server)
    server.plan = [(200, {}, _hello([]))]
    t.hello()
    assert t._wire.open_connections() == 1
    t.close()
    assert t._wire.open_connections() == 0
