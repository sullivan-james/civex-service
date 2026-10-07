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

The one optional extra is the desktop tray app, which pulls in
platform-specific GUI packages:

```bash
uv tool install "civex[desktop]"
```

Verify the install:

```bash
civex --version
civex --help
```

## Updating

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
