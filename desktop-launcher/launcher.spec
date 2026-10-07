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
# Environment:
#   CIVEX_LAUNCHER_UV    the uv binary to bundle (on macOS, a universal one
#                        made with `lipo` for a universal2 build)
#   CIVEX_LAUNCHER_ARCH  macOS only: `universal2` for one app that runs on
#                        Intel and Apple silicon (needs a universal2 Python,
#                        such as python.org's)
#   CIVEX_APP_VERSION    the civex version this is released with, for the
#                        app's version details (else 0.0.0)
#
# Produces, in dist/:
#   macOS    civex.app (put in a disk image by the release workflow)
#   Windows  civex/ with civex.exe (packed by desktop-launcher/windows/civex.iss)
#   Linux    civex (one file)

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(SPEC))  # noqa: F821 (PyInstaller sets SPEC)
ASSETS = os.path.join(HERE, "assets")
uv = os.environ["CIVEX_LAUNCHER_UV"]
version = os.environ.get("CIVEX_APP_VERSION") or "0.0.0"
# The numeric part, for fields that take only numbers ("1.3.0rc1" -> 1.3.0).
numbers = [int(n) for n in re.findall(r"\d+", version.split("rc")[0])][:3]
numbers += [0] * (3 - len(numbers))
plain = ".".join(str(n) for n in numbers)

# The civex version this app is released with, inside the app: the launcher
# installs at least that one (`civex[desktop]>=<it>`), not whatever is newest
# and stable on PyPI, which for a pre-release's app was an older civex.
# Left out for a build without one (a dry run): it then takes the newest.
released = []
if os.environ.get("CIVEX_APP_VERSION"):
    os.makedirs(workpath, exist_ok=True)  # noqa: F821 (PyInstaller sets workpath)
    stamp = os.path.join(workpath, "civex_version.txt")  # noqa: F821
    with open(stamp, "w", encoding="utf-8") as f:
        f.write(os.environ["CIVEX_APP_VERSION"])
    released = [(stamp, ".")]

a = Analysis(
    [os.path.join(HERE, "civex_launcher.py")],
    pathex=[],
    binaries=[(uv, "uv")],
    # The logo the launcher's window shows (and uses as its icon).
    datas=released + [(os.path.join(ASSETS, "civex.png"), ".")],
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
        target_arch=os.environ.get("CIVEX_LAUNCHER_ARCH") or None,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="civex", upx=False)
    app = BUNDLE(
        coll,
        name="civex.app",
        bundle_identifier="org.civex.desktop",
        icon=os.path.join(ASSETS, "civex.icns"),
        version=plain,
        info_plist={
            "CFBundleDisplayName": "civex",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": plain,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
        },
    )
elif sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    four = (*numbers, 0)
    details = VSVersionInfo(
        ffi=FixedFileInfo(filevers=four, prodvers=four),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("CompanyName", "civex"),
                            StringStruct("FileDescription", "civex"),
                            StringStruct("FileVersion", version),
                            StringStruct("InternalName", "civex"),
                            StringStruct("OriginalFilename", "civex.exe"),
                            StringStruct("ProductName", "civex"),
                            StringStruct("ProductVersion", version),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )
    # A folder build: the installer puts it in place, so the app doesn't
    # unpack itself into a temporary folder on every start (slow, and slower
    # still with antivirus scanning each unpacked file).
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="civex",
        console=False,  # no terminal window on double-click
        upx=False,
        icon=os.path.join(ASSETS, "civex.ico"),
        version=details,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="civex", upx=False)
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        name="civex",
        console=False,
        upx=False,
    )
