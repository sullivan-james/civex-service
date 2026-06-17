# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for civex desktop + CLI bundles.
#
# Produces two standalone one-file executables:
#   dist/civex-desktop  — native webview window (double-click to run)
#   dist/civex          — console CLI (same as pip-installed `civex`)
#
# Build:
#   pip install ".[postgres,workflows,server,desktop]" pyinstaller
#   cd frontend && npm ci && npm run build && cd ..
#   pyinstaller civex.spec
#
# Platform notes:
#   macOS   — uses WKWebView (built into macOS, no extras needed)
#   Windows — uses WebView2 (Edge Chromium, ships with Win 10/11 since 2021)
#   Linux   — uses WebKitGTK; users need: libwebkit2gtk-4.0 or libwebkitgtk-6.0

from PyInstaller.utils.hooks import collect_submodules

# Collect every civex.* submodule — avoids missing any module that is only
# referenced by string (e.g. "civex.server.app:app" passed to uvicorn.run).
_CIVEX_ALL = collect_submodules("civex")

_HIDDEN = _CIVEX_ALL + [
    # uvicorn internals are imported dynamically
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on",
    # SQLAlchemy dialect loaded by URL string
    "sqlalchemy.dialects.sqlite",
    # pywebview platform backends (loaded by name at runtime based on OS)
    "webview.platforms.cocoa",        # macOS
    "webview.platforms.winforms",     # Windows
    "webview.platforms.edgechromium", # Windows (WebView2)
    "webview.platforms.gtk",          # Linux
]

_DATAS = [
    # Built React app — server/app.py finds it at sys._MEIPASS/frontend_dist/
    ("frontend/dist", "frontend_dist"),
]

# ── Desktop tray app ──────────────────────────────────────────────────────────

a_gui = Analysis(
    ["src/civex/desktop/tray.py"],
    pathex=["src"],
    binaries=[],
    datas=_DATAS,
    hiddenimports=_HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data)

exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    a_gui.binaries,
    a_gui.zipfiles,
    a_gui.datas,
    name="civex-desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # no terminal window on double-click
    icon=None,       # replace with "assets/civex.icns" / "assets/civex.ico" when available
)

# ── CLI ───────────────────────────────────────────────────────────────────────

a_cli = Analysis(
    ["src/civex/desktop/cli_entry.py"],
    pathex=["src"],
    binaries=[],
    datas=_DATAS,
    hiddenimports=_HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["webview"],   # not needed for CLI-only binary
    noarchive=False,
)

pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data)

exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    a_cli.binaries,
    a_cli.zipfiles,
    a_cli.datas,
    name="civex",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,    # keep terminal output for CLI
    icon=None,
)
