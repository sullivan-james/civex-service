# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the civex desktop app: the launcher (civex_launcher.py)
# and the uv it installs and updates civex with. civex itself is not in here;
# the launcher installs it from PyPI on first start, so this app stays small
# and never needs rebuilding to get a new civex.
#
# Build (from the repo root):
#   CIVEX_LAUNCHER_UV="$(command -v uv)" pyinstaller desktop-launcher/launcher.spec
#
# Produces dist/civex.app on macOS, dist/civex.exe on Windows, dist/civex on
# Linux (which also needs WebKitGTK for the desktop window, as pywebview does).

import os
import sys

uv = os.environ["CIVEX_LAUNCHER_UV"]

a = Analysis(
    ["civex_launcher.py"],
    pathex=[],
    binaries=[(uv, "uv")],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # An app bundle needs a folder build (one-file .app is deprecated).
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="civex",
        console=False,
        upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="civex", upx=False)
    app = BUNDLE(
        coll,
        name="civex.app",
        bundle_identifier="org.civex.desktop",
        icon=None,  # "assets/civex.icns" when there is one
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        name="civex",
        console=False,  # no terminal window on double-click
        upx=False,
        icon=None,  # "assets/civex.ico" when there is one
    )
