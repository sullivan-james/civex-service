"""Desktop launcher: native webview window + embedded uvicorn server."""
from __future__ import annotations

import os
import threading
import time
import urllib.request
from pathlib import Path

from sqlalchemy import create_engine

_URL = "http://127.0.0.1:8000"

_LOADING_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    height: 100vh; background: #f6f8fa; color: #656d76;
  }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
         background: #0a7ea4; margin: 0 3px;
         animation: pulse 1.2s ease-in-out infinite; }
  .dot:nth-child(2) { animation-delay: 0.2s; }
  .dot:nth-child(3) { animation-delay: 0.4s; }
  @keyframes pulse { 0%,80%,100% { opacity: 0.2; } 40% { opacity: 1; } }
  p { margin-top: 16px; font-size: 13px; }
</style>
</head>
<body>
  <div><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>
  <p>Starting civex&hellip;</p>
</body>
</html>"""


def _auto_init(project: Path) -> None:
    """Create ~/civex/.civex/ with a default SQLite config on first run."""
    civex_dir = project / ".civex"
    if civex_dir.exists():
        return

    project.mkdir(parents=True, exist_ok=True)
    civex_dir.mkdir()
    (civex_dir / "workflows").mkdir()
    (civex_dir / "plugins").mkdir()
    (civex_dir / "objects").mkdir()

    db_path = civex_dir / "project.db"
    (civex_dir / "config.toml").write_text(f'[db]\nurl = "sqlite:///{db_path}"\n')

    # Initialise DB schema directly (bypasses the cached _engine singleton)
    from civex.db.models import Base
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()


def _run_server() -> None:
    import uvicorn
    uvicorn.run("civex.server.app:app", host="127.0.0.1", port=8000, log_level="warning")


def _wait_for_server(timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"{_URL}/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def main() -> None:
    import webview

    home_project = Path.home() / "civex"
    _auto_init(home_project)

    # Set CWD so find_project_root() walks up and finds .civex/
    os.chdir(home_project)

    threading.Thread(target=_run_server, daemon=True).start()

    window = webview.create_window(
        "civex",
        html=_LOADING_HTML,
        width=1280,
        height=800,
        min_size=(800, 600),
    )

    def _navigate_when_ready():
        if _wait_for_server():
            window.load_url(_URL)
        else:
            window.load_html(
                "<body style='font-family:sans-serif;padding:2rem'>"
                "<h2>civex failed to start</h2>"
                "<p>The server did not respond within 30 seconds.</p>"
                "</body>"
            )

    # pywebview calls func in a background thread after the GUI is initialised
    webview.start(func=_navigate_when_ready)


if __name__ == "__main__":
    main()
