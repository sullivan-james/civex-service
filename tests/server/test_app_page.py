"""The app's page is made one way wherever it is served: at `/` by civex, or
under a host's path with a boot object (`server/app_page.py`)."""

from __future__ import annotations

import json
import re

import pytest

from civex.server.app_page import normalise_base, render_app_page

PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <base href="/" />
    <title>civex</title>
    <script type="module" src="./assets/index-abc.js"></script>
  </head>
  <body><div id="root"></div></body>
</html>
"""


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "index.html").write_text(PAGE)
    return tmp_path


def _boot(page: str):
    found = re.search(r"window.__CIVEX__ = (.*?)</script>", page)
    return json.loads(found.group(1)) if found else None


def test_at_the_root_the_page_is_as_built(dist):
    page = render_app_page(dist)
    assert '<base href="/" />' in page
    assert _boot(page) is None
    assert "./assets/index-abc.js" in page


def test_a_host_serves_it_under_its_own_path_with_a_boot_object(dist):
    page = render_app_page(
        dist,
        base="/p/acme/survey",
        boot={"login_url": "/login", "extensions": ["/ext/hub.js"]},
    )
    assert '<base href="/p/acme/survey/" />' in page
    assert page.count("<base") == 1
    assert _boot(page) == {"extensions": ["/ext/hub.js"], "login_url": "/login"}
    # In the head, before the app's own script runs.
    assert page.index("__CIVEX__") < page.index("</head>")


def test_nothing_in_the_boot_object_can_close_the_script(dist):
    page = render_app_page(dist, boot={"name": "</script><script>alert(1)</script>"})
    assert "</script><script>alert(1)" not in page
    assert _boot(page) == {"name": "</script><script>alert(1)</script>"}


def test_a_build_without_a_base_gets_one(tmp_path):
    (tmp_path / "index.html").write_text(PAGE.replace('    <base href="/" />\n', ""))
    page = render_app_page(tmp_path, base="/p/a/b/")
    assert '<base href="/p/a/b/" />' in page


def test_a_base_names_a_folder():
    assert normalise_base("/") == "/"
    assert normalise_base("/p/a/b") == "/p/a/b/"
    with pytest.raises(ValueError):
        normalise_base("p/a")
