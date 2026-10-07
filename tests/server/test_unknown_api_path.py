"""An address under /api that the server doesn't have answers 404 with a
reason, never the web app's page (which a browser would then fail to read as
data: "Unexpected token '<'")."""

from __future__ import annotations

import pytest

from civex.server import app as app_module


@pytest.mark.skipif(
    not (app_module._DIST / "index.html").exists(), reason="no built frontend"
)
def test_an_unknown_api_address_is_not_found_and_pages_are_the_app(client):
    missing = client.get("/api/no-such-thing")
    assert missing.status_code == 404
    assert "has no /api/no-such-thing" in missing.json()["detail"]
    assert client.get("/api").status_code == 404

    page = client.get("/records/anything")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    # Checked with the server each time, so an update is never hidden by a
    # copy the browser kept.
    assert page.headers["cache-control"] == "no-cache"
