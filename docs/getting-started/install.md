# Install

civex is published on PyPI as [`civex`](https://pypi.org/project/civex/). The
recommended way to install it is [uv](https://docs.astral.sh/uv/), which
**doesn't need Python on your computer**: it downloads a suitable Python
(3.12 or newer) by itself and keeps civex in its own environment. civex also
uses uv to run custom plugins, so installing it this way sets that up too.

**1. Install uv** (once per computer):

=== "macOS / Linux"

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

=== "Windows"

    In PowerShell:

    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

Open a new terminal afterwards so `uv` is on your PATH. (Already have
Homebrew, WinGet or pipx? `brew install uv`, `winget install --id=astral-sh.uv -e`
or `pipx install uv` work too.)

**2. Install civex:**

```bash
uv tool install civex
```

If the terminal then says `civex` isn't found, run `uv tool update-shell` and
open a new terminal.

??? note "Other ways to install"

    If you already manage Python yourself, civex installs like any other
    package (Python 3.12 or newer):

    === "pipx"

        ```bash
        pipx install civex
        ```

    === "pip"

        ```bash
        python -m venv venv && source venv/bin/activate
        pip install civex
        ```

    Custom plugins still need `uv` on your PATH; `civex doctor` says whether it
    was found.

Everything is included: the HTTP API and web UI, workflow execution, the
PostgreSQL driver, AI-assisted commands and telemetry. There's nothing to
choose. (`civex[server]` and the other old extra names still install fine —
they're now no-ops — so existing scripts and installs keep working.)

## The desktop app

For people who'd rather not use a terminal at all, the desktop app opens civex
in its own window with a project picker. Download it from the release page:

=== "Windows"

    `civex-<version>-windows-setup.exe`. Run it: it installs for you only, so it doesn't
    ask for an administrator, and adds civex to the Start menu (and, if you
    tick it, the Desktop). Uninstall it from **Settings → Apps**.

    The installer isn't signed yet, so Windows may say *Windows protected your
    PC*: choose **More info**, then **Run anyway**.

=== "macOS"

    `civex-<version>-macos.dmg`, one download for Intel and Apple silicon Macs (macOS 11
    or later). Open it and drag **civex** into **Applications**.

    The app isn't signed yet, so the first time you open it macOS says it
    can't check it. Click **Done**, then open **System Settings → Privacy &
    Security**, scroll to *civex was blocked*, and click **Open Anyway**. You
    only do this once.

The first time it starts it sets civex up, which needs an internet connection
and takes a minute or two: it downloads civex and the Python it runs on into a
folder of its own (`%LOCALAPPDATA%\civex\app` on Windows,
`~/Library/Application Support/civex/app` on macOS, `~/.local/share/civex/app`
on Linux), separate from any civex you installed yourself. After that it starts
straight away, and keeps itself up to date from **Settings → Updates**. On
Windows the installer does this setup, so the first start opens straight into
the app. Its logs are in the `logs` folder inside that folder.

To use the app's civex in a terminal too, tick **Add the civex command to
PATH** in the Windows installer (on by default), or use **Settings → Updates →
Command line** in the app on any system: it adds the app's `civex` to your PATH
on Windows, or links it into `~/.local/bin` on macOS and Linux. Open a new
terminal afterwards. If you also installed civex with uv, the section says
which copy a terminal would find first.

!!! warning "Linux"
    The desktop window doesn't open on Linux yet: it needs a GTK or Qt window
    backend that isn't installed with it. The Linux download still installs
    civex; use it from a terminal (`~/.local/share/civex/app/bin/civex serve
    --open`) until it does.

The desktop window can also be installed alongside the command line:

```bash
uv tool install "civex[desktop]"
civex desktop
```

Verify the install:

```bash
civex --version
civex --help
```

## Updating

In the app, **Settings → Updates** checks for a newer version and updates with
one click: civex closes, installs it and starts again, and the page reloads.
The status bar says when one is available. This works for the desktop app and
for `civex serve` installed with uv, pipx or pip. From a terminal:

```bash
civex update           # install the latest release
civex update --check   # only report whether one is available
```

(`uv tool upgrade civex` does the same for a uv install.)

Pre-releases (release candidates, for trying what's coming) are only
installed if you ask: `civex update --pre`. Once you're on one, a plain
`civex update` moves you on when the final release is out.

`civex update` detects whether civex was installed with pipx, `uv tool` or pip
and runs the matching upgrade. Restart `civex serve` afterwards if it's
running. Project databases migrate themselves the next time they're opened.
`civex update` confirms the installed version actually changed, and says so if
it didn't. It also checks that every package civex needs is installed (even
when you're already up to date) and reinstalls any that are missing, and warns
if typing `civex` still runs an older copy found earlier on your PATH.

## Troubleshooting

```bash
civex doctor
```

checks the install: whether another copy of civex shadows this one on PATH,
whether the required packages are present, whether `uv` is found, and whether
a custom plugin's Python can start. It also finds cached plugin environments left pointing at a Python that no
longer exists; `civex doctor --fix` removes them. Each problem comes with what
to do about it.
Inside a project it also checks the data.

## Next step

[Create your first project →](first-project.md)
