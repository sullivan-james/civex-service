"""Desktop launcher: project picker welcome screen + per-project native window."""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

from civex.project import scaffold_project

if TYPE_CHECKING:
    import webview

# Stored alongside other per-user config, outside any project directory.
_RECENT_FILE = Path.home() / ".config" / "civex" / "recent.json"
#: Set by the desktop launcher: the folder it keeps its logs in (in AppData on
#: Windows), so the app's log is beside the launcher's.
LOG_DIR_ENV = "CIVEX_LOG_DIR"


def _log_file() -> Path:
    folder = os.environ.get(LOG_DIR_ENV)
    base = Path(folder) if folder else Path.home() / ".config" / "civex"
    return base / "civex-desktop.log"


_LOG_FILE = _log_file()

# Set in main() before webview.start() so Api methods can reference it.
_window: "webview.Window | None" = None


def _setup_logging() -> None:
    """Log to the log file. Without a terminal (started by the launcher, or
    from a Start-menu or Dock icon) everything printed goes there too: on
    Windows the app has no console at all (it is a GUI script), so the
    server's own output would otherwise be lost."""
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = open(_LOG_FILE, "a", buffering=1, encoding="utf-8")  # noqa: SIM115
    terminal = sys.stdout is not None and sys.stdout.isatty()
    if not terminal:
        sys.stdout = sys.stderr = log
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(log),
            *([logging.StreamHandler()] if terminal else []),
        ],
    )


_log = logging.getLogger("civex.desktop")


# ── Recent-projects list ──────────────────────────────────────────────────────


def _load_recent() -> list[dict]:
    try:
        items = json.loads(_RECENT_FILE.read_text())
        # Drop entries whose project directory no longer exists.
        return [i for i in items if (Path(i["path"]) / "_civex").exists()]
    except Exception:
        return []


def _save_recent(path: Path) -> None:
    items = _load_recent()
    entry = {"path": str(path), "name": path.name}
    items = [i for i in items if i["path"] != str(path)]  # deduplicate
    items.insert(0, entry)
    _RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _RECENT_FILE.write_text(json.dumps(items[:10], indent=2))


def _remove_from_recent(path_str: str) -> None:
    items = _load_recent()
    _RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _RECENT_FILE.write_text(
        json.dumps([i for i in items if i["path"] != path_str], indent=2)
    )


# ── Project initialisation ────────────────────────────────────────────────────


def _init_project(path: Path) -> None:
    """Create a _civex/ directory inside path, initialising the SQLite DB."""
    try:
        scaffold_project(path)
    except FileExistsError:
        pass  # already initialised — open it as-is


def _resolve_data_dir() -> Path:
    """Directory to reveal for 'open data folder' — the SQLite file's folder if
    local, otherwise the project's _civex/ directory (config, objects, logs)."""
    from civex.config import load_config

    config = load_config()
    prefix = "sqlite:///"
    if config.db.url.startswith(prefix):
        db_path = Path(config.db.url[len(prefix) :])
        if not db_path.is_absolute():
            db_path = config.project_root / db_path
        return db_path.parent
    return config.civex_dir


def _reveal_in_file_manager(path: Path) -> None:
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"Directory not found: {path}")
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=True)
    else:
        subprocess.run(["xdg-open", str(path)], check=True)


# ── Server ────────────────────────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_server(port: int, errors: list[str]) -> None:
    import asyncio
    import uvicorn

    # On Windows the default ProactorEventLoop must be set explicitly in a
    # non-main thread; without this uvicorn.run() can silently fail.
    if sys.platform == "win32":
        asyncio.set_event_loop(asyncio.ProactorEventLoop())
    _log.info("Starting uvicorn on port %d", port)
    try:
        uvicorn.run(
            "civex.server.app:app", host="127.0.0.1", port=port, log_level="warning"
        )
    except Exception as exc:
        _log.exception("Server failed to start on port %d", port)
        errors.append(str(exc))


def _wait_for_server(url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"{url}/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def _launch_project(path: Path) -> dict:
    """Start the server for path and navigate the window to it."""
    _save_recent(path)
    os.chdir(path)

    port = _free_port()
    url = f"http://127.0.0.1:{port}"

    errors: list[str] = []
    threading.Thread(target=_run_server, args=(port, errors), daemon=True).start()

    def _navigate() -> None:
        assert _window is not None
        if _wait_for_server(url):
            _window.resize(1280, 800)
            _window.load_url(url)
        else:
            detail = errors[0] if errors else "The server did not respond within 30 s."
            _window.load_html(
                "<body style='font-family:sans-serif;padding:2rem;color:#d1242f'>"
                "<h2>Failed to start server</h2>"
                f"<pre style='white-space:pre-wrap;font-size:13px'>{detail}</pre>"
                "<p style='margin-top:1rem;color:#57606a;font-size:13px'>"
                "Check that all civex dependencies are installed: "
                '<code>pip install -e ".[server]"</code></p>'
                "</body>"
            )

    threading.Thread(target=_navigate, daemon=True).start()
    return {"ok": True}


# ── JS bridge ─────────────────────────────────────────────────────────────────


class _Api:
    def get_recent(self) -> list[dict]:
        return _load_recent()

    def open_project(self) -> dict | None:
        import webview

        assert _window is not None
        result = _window.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
        if not result:
            return None
        path = Path(result[0])
        if not (path / "_civex").exists():
            return {
                "error": f"'{path.name}' is not a civex project — use Create project to initialise it."
            }
        return _launch_project(path)

    def create_project(self) -> dict | None:
        import webview

        assert _window is not None
        result = _window.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
        if not result:
            return None
        _init_project(Path(result[0]))
        return _launch_project(Path(result[0]))

    def open_recent(self, path_str: str) -> dict:
        path = Path(path_str)
        if not path.exists() or not (path / "_civex").exists():
            _remove_from_recent(path_str)
            return {"error": f"Project not found: {path_str}"}
        return _launch_project(path)

    def remove_recent(self, path_str: str) -> dict:
        _remove_from_recent(path_str)
        return {"ok": True}

    def browse_folder(self) -> dict:
        """Open a native folder picker and return the selected path (forward slashes)."""
        import webview

        assert _window is not None
        result = _window.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
        if not result:
            return {"path": None}
        return {"path": str(result[0]).replace("\\", "/")}

    def open_data_dir(self) -> dict:
        """Reveal the current project's database directory in Explorer/Finder/the file manager."""
        try:
            _reveal_in_file_manager(_resolve_data_dir())
            return {"ok": True}
        except Exception as e:
            _log.exception("Failed to open data directory")
            return {"error": str(e)}


# ── Welcome screen HTML ───────────────────────────────────────────────────────

_WELCOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>civex</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: #f6f8fa;
    color: #1f2328;
    height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    -webkit-user-select: none;
    user-select: none;
  }

  .wrap {
    width: 100%;
    max-width: 600px;
    padding: 0 32px;
  }

  /* ── Header ── */
  .header { text-align: center; margin-bottom: 36px; }

  .logo {
    width: 52px; height: 52px;
    background: #0969da;
    border-radius: 13px;
    margin: 0 auto 14px;
    display: flex; align-items: center; justify-content: center;
    font-size: 26px; font-weight: 700; color: white; letter-spacing: -0.5px;
  }

  h1 { font-size: 26px; font-weight: 700; letter-spacing: -0.5px; }

  .tagline { margin-top: 5px; font-size: 13px; color: #656d76; }

  /* ── Action buttons ── */
  .actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 32px; }

  .action-btn {
    padding: 16px 18px;
    border-radius: 8px;
    border: 1px solid #d0d7de;
    background: white;
    cursor: pointer;
    text-align: left;
    font-family: inherit;
    transition: border-color .15s, background .15s, box-shadow .15s;
  }

  .action-btn:hover {
    border-color: #0969da;
    background: #f0f6ff;
    box-shadow: 0 0 0 3px rgba(9,105,218,.12);
  }

  .action-btn:active { background: #dbe9ff; }

  .action-btn:disabled { opacity: .5; cursor: not-allowed; }

  .btn-icon { font-size: 20px; margin-bottom: 8px; display: block; }
  .btn-label { font-size: 13px; font-weight: 600; color: #1f2328; display: block; }
  .btn-desc  { font-size: 11px; color: #656d76; margin-top: 2px; display: block; }

  /* ── Error banner ── */
  .error-banner {
    background: #ffebe9; border: 1px solid #ffcecb; border-radius: 6px;
    padding: 10px 14px; font-size: 12px; color: #d1242f;
    margin-bottom: 12px; display: none;
  }
  .error-banner.show { display: block; }

  /* ── Recent projects ── */
  .recent-label {
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: .6px; color: #656d76; margin-bottom: 8px;
  }

  .recent-list {
    border: 1px solid #d0d7de; border-radius: 8px;
    background: white; overflow: hidden;
  }

  .recent-item {
    display: flex; align-items: center;
    padding: 11px 14px;
    border-bottom: 1px solid #f0f2f4;
    cursor: pointer;
    transition: background .1s;
  }
  .recent-item:last-child { border-bottom: none; }
  .recent-item:hover { background: #f6f8fa; }
  .recent-item:hover .rm { opacity: 1; }

  .ri-icon { font-size: 15px; margin-right: 11px; flex-shrink: 0; color: #656d76; }

  .ri-info { flex: 1; min-width: 0; }
  .ri-name {
    font-size: 13px; font-weight: 600; color: #1f2328;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .ri-path {
    font-size: 11px; color: #818b98; margin-top: 1px;
    font-family: "SFMono-Regular", Consolas, monospace;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }

  .rm {
    opacity: 0; background: none; border: none; cursor: pointer;
    padding: 3px 7px; color: #818b98; font-size: 15px; border-radius: 4px;
    flex-shrink: 0; font-family: inherit; line-height: 1;
    transition: opacity .1s, color .1s, background .1s;
  }
  .rm:hover { color: #d1242f; background: #ffebe9; }

  .empty {
    padding: 22px 14px; text-align: center;
    font-size: 12px; color: #818b98; font-style: italic;
  }

  /* ── Loading overlay ── */
  .loading {
    position: fixed; inset: 0;
    background: rgba(246,248,250,.93);
    display: none; flex-direction: column;
    align-items: center; justify-content: center; gap: 14px;
  }
  .loading.show { display: flex; }

  .spinner {
    width: 28px; height: 28px;
    border: 3px solid #d0d7de; border-top-color: #0969da;
    border-radius: 50%;
    animation: spin .7s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  .loading-msg { font-size: 13px; color: #656d76; }
</style>
</head>
<body>

<div class="wrap">
  <div class="header">
    <div class="logo">c</div>
    <h1>civex</h1>
    <p class="tagline">Research data management</p>
  </div>

  <div id="err" class="error-banner"></div>

  <div class="actions">
    <button class="action-btn" id="btn-open" onclick="doOpen()">
      <span class="btn-icon">📂</span>
      <span class="btn-label">Open project</span>
      <span class="btn-desc">Select an existing civex project folder</span>
    </button>
    <button class="action-btn" id="btn-create" onclick="doCreate()">
      <span class="btn-icon">✦</span>
      <span class="btn-label">Create project</span>
      <span class="btn-desc">Initialise a new civex project in a folder</span>
    </button>
  </div>

  <p class="recent-label">Recent</p>
  <div class="recent-list" id="recent"></div>
</div>

<div class="loading" id="loading">
  <div class="spinner"></div>
  <p class="loading-msg" id="loading-msg">Opening project…</p>
</div>

<script>
  function esc(s) {
    return String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function showErr(msg, duration) {
    const el = document.getElementById('err');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove('show'), duration || 6000);
  }

  function showLoading(msg) {
    document.getElementById('loading-msg').textContent = msg || 'Opening project…';
    document.getElementById('loading').classList.add('show');
  }

  function setBusy(on) {
    ['btn-open','btn-create'].forEach(id => {
      document.getElementById(id).disabled = on;
    });
  }

  function renderRecent(items) {
    const el = document.getElementById('recent');
    if (!items || !items.length) {
      el.innerHTML = '<div class="empty">No recent projects</div>';
      return;
    }
    el.innerHTML = items.map(item => `
      <div class="recent-item" data-path="${esc(item.path)}" onclick="doOpenRecent(this.dataset.path)">
        <span class="ri-icon">⬡</span>
        <div class="ri-info">
          <div class="ri-name">${esc(item.name)}</div>
          <div class="ri-path">${esc(item.path)}</div>
        </div>
        <button class="rm" title="Remove from list"
          data-path="${esc(item.path)}"
          onclick="doRemove(event,this.dataset.path)">×</button>
      </div>`).join('');
  }

  async function loadRecent() {
    renderRecent(await window.pywebview.api.get_recent());
  }

  async function doOpen() {
    setBusy(true);
    const r = await window.pywebview.api.open_project();
    if (!r) { setBusy(false); return; }
    if (r.error) { showErr(r.error); setBusy(false); return; }
    showLoading('Opening project…');
  }

  async function doCreate() {
    setBusy(true);
    const r = await window.pywebview.api.create_project();
    if (!r) { setBusy(false); return; }
    if (r.error) { showErr(r.error); setBusy(false); return; }
    showLoading('Creating project…');
  }

  async function doOpenRecent(pathStr) {
    const r = await window.pywebview.api.open_recent(pathStr);
    if (!r) return;
    if (r.error) { showErr(r.error); loadRecent(); return; }
    showLoading('Opening project…');
  }

  async function doRemove(e, pathStr) {
    e.stopPropagation();
    await window.pywebview.api.remove_recent(pathStr);
    loadRecent();
  }

  window.addEventListener('pywebviewready', loadRecent);
</script>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────


def _project_arg(argv: list[str]) -> Path | None:
    """`--project PATH`: the project to open at once, as the launcher passes
    it after an update; None when absent or no longer a project."""
    if "--project" not in argv:
        return None
    i = argv.index("--project")
    if i + 1 >= len(argv):
        return None
    path = Path(argv[i + 1])
    return path if (path / "_civex").exists() else None


def _storage_dir() -> str:
    """Where the app's window keeps what its pages store: in the launcher's
    folder when the launcher started it (beside `logs`), else beside the
    recent-projects list."""
    logs = os.environ.get(LOG_DIR_ENV)
    folder = (Path(logs).parent if logs else _RECENT_FILE.parent) / "webview"
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder)


def main() -> None:
    global _window
    import webview

    from civex.updates import on_quit_for_update

    _setup_logging()
    _log.info("civex desktop starting (log: %s)", _LOG_FILE)

    api = _Api()
    _window = webview.create_window(
        "civex",
        html=_WELCOME_HTML,
        js_api=api,
        width=680,
        height=580,
        min_size=(560, 480),
        resizable=True,
    )
    # Updating from the app (civex.updates): close, and the launcher that
    # started this app updates it and starts it again.
    on_quit_for_update(lambda: _window.destroy() if _window else None)
    # Servers stopped so this app could update start again now, whether or not
    # the update worked (the launcher that updated it can't: it predates them).
    from civex import running

    for record in running.start_remembered():
        _log.info("Started again after an update: %s", record.describe())
    project = _project_arg(sys.argv[1:])
    # Not private: what the pages keep (pins, recent items, choices such as
    # dismissing a notice or including pre-releases) lasts from one opening
    # of the app to the next, in a folder of the app's own.
    storage = _storage_dir()
    if project is not None:
        webview.start(
            lambda: _launch_project(project),
            private_mode=False,
            storage_path=storage,
        )
    else:
        webview.start(private_mode=False, storage_path=storage)


if __name__ == "__main__":
    main()
