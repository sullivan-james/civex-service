# Install

Two ways in: the **desktop app** (no terminal needed) or the **command line**.
Both include everything: the web app, workflows, PostgreSQL support and the CLI.

## Command line (recommended)

civex installs with [uv](https://docs.astral.sh/uv/), which brings its own
Python (3.12+), so you don't need one.

**1. Install uv**, once per computer:

=== "macOS / Linux"

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

=== "Windows (PowerShell)"

    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

Open a new terminal afterwards. (`brew install uv`, `winget install --id=astral-sh.uv -e`
and `pipx install uv` work too.)

**2. Install civex:**

```bash
uv tool install civex
civex --version
```

`civex: command not found`? Run `uv tool update-shell` and open a new terminal.

??? note "pipx or pip instead"

    ```bash
    pipx install civex
    # or, in a virtual environment:
    pip install civex
    ```

    Custom plugins still need `uv` on your PATH. `civex doctor` says whether it's
    found.

## Desktop app

Download it from the release page. It opens civex in its own window, with a
project picker.

=== "Windows"

    Run `civex-<version>-windows-setup.exe`. It installs for you only (no
    administrator needed). The installer isn't signed yet: if Windows says
    *Windows protected your PC*, choose **More info → Run anyway**.

=== "macOS"

    Open `civex-<version>-macos.dmg` and drag **civex** into **Applications**
    (macOS 11+, Intel and Apple silicon). It isn't signed yet: the first time,
    click **Done**, then **System Settings → Privacy & Security → Open Anyway**.

=== "Linux"

    The window doesn't open on Linux yet. The download still installs civex, so
    run `~/.local/share/civex/app/bin/civex serve --open` and use it in your
    browser.

The first start downloads civex and its Python (a minute or two, online), into a
folder of its own, separate from any `uv` install. To use the app's copy from a
terminal, use **Settings → Updates → Command line** (on Windows, the installer's
*Add the civex command to PATH*).

With civex already installed by uv, `uv tool install "civex[desktop]"` then
`civex desktop` opens the same window.

## Updating

```bash
civex update           # the latest release
civex update --check   # just say whether there is one
civex update --pre     # include release candidates
```

In the app: **Settings → Updates**, or the notice in the status bar. Either way:

- It works out how civex was installed (uv, pipx, pip, the desktop app) and
  updates that copy.
- Servers running from that copy are stopped, and started again afterwards with
  the same command (it asks first; `--yes` skips that).
- Projects update their databases the next time they open.

## Something wrong?

```bash
civex doctor          # add --fix to clean up stale plugin environments
```

It checks for another `civex` earlier on your PATH, missing packages, `uv`, and
whether custom plugins can start. Run inside a project, it checks the project's
data too. Each problem comes with the fix.

**Next:** [Your first project →](first-project.md)
