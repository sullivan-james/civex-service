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

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

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
    # Loaded by referencing._core at import time to resolve $schema/$ref in a
    # plugin's declared config schema (see _DATAS below)
    "jsonschema_specifications",
]

_DATAS = [
    # Built React app — server/app.py finds it at sys._MEIPASS/frontend_dist/
    ("frontend/dist", "frontend_dist"),
    # jsonschema-specifications keeps the JSON Schema metaschemas as *package
    # data*, read through importlib.resources rather than imported — so
    # collect_submodules/hiddenimports alone don't bring them along, and a
    # bundler that drops them produces a build that succeeds, passes every
    # test from source, and then fails only inside the frozen app, the first
    # time someone saves a workflow (workflows/contract_validation.py
    # validates each step's config against its plugin's declared schema).
    # pyinstaller-hooks-contrib probably handles this already; declaring it
    # here costs nothing and doesn't depend on that staying true.
    *collect_data_files("jsonschema_specifications"),
    # Alembic finds migrations by walking a directory on disk (env.py,
    # script.py.mako, versions/*.py), not by importing them, so the modules
    # collect_submodules puts in the archive aren't enough: without these
    # files every frozen build failed `civex init` (db/migrate.py).
    ("src/civex/db/migrations", "civex/db/migrations"),
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
