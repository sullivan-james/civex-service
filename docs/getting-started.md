# Getting started

## Installation

=== "Desktop app"

    Each release includes a ZIP for macOS, Windows, and Linux containing both `civex-desktop` (a native window with the web UI, starting its own server automatically) and the `civex` CLI. No terminal required for the desktop app.

    **macOS:** download the macOS ZIP from the [latest release](https://github.com/CivexData/civex-service/releases/latest), unzip, move `civex-desktop` to Applications (or anywhere), then right-click → **Open** on first launch to bypass the Gatekeeper warning.

    **Windows:** download the Windows ZIP, unzip anywhere, and double-click `civex-desktop.exe`. Requires the Edge WebView2 runtime, which ships with Windows 10 (2021 update) and Windows 11 — if missing, get it from [microsoft.com/en-us/edge/webview2](https://developer.microsoft.com/microsoft-edge/webview2/).

    **Linux:** unzip and `chmod +x` the binaries. Requires WebKitGTK (`sudo apt install libwebkit2gtk-4.0` on Debian/Ubuntu, or `libwebkitgtk-6.0` on newer releases).

    On first launch, civex asks you to choose a project folder and initialises it automatically.

    If you also want the CLI, move the `civex` binary from the same ZIP onto your `PATH`.

=== "pipx (CLI only)"

    ```bash
    pip install pipx
    pipx ensurepath        # adds civex to PATH — open a new terminal after this
    ```

    Download the latest release wheel and install:

    ```bash
    gh release download --repo CivexData/civex-service --pattern "*.whl"
    pipx install "./civex-0.1.0-py3-none-any.whl[server]"
    ```

    To upgrade, re-run `pipx install --force` with the new wheel.

=== "From source (development)"

    ```bash
    git clone https://github.com/CivexData/civex-service
    cd civex-service
    python -m venv venv && source venv/bin/activate
    pip install -e ".[postgres,workflows,server]"
    ```

Verify the install:

```bash
civex --version
civex --help
```

## Initialise a project

Navigate to your project directory and run:

```bash
civex init
```

This creates a `_civex/` directory with:

```
_civex/
  config.toml     # database URL and optional remote config
  civex.db        # SQLite database (if not using PostgreSQL)
  objects/        # content-addressed file storage
  workflows/      # YAML workflow definitions
  plugins/        # custom Python plugins
```

By default, `civex init` tries to set up a **Docker-managed PostgreSQL** container automatically (if a PostgreSQL driver and Docker are both available), falling back to SQLite otherwise. Force SQLite explicitly with:

```bash
civex init --sqlite
```

To connect to an existing PostgreSQL server instead of a Docker-managed one, run `civex db setup-postgres` after `civex init` (auto-detects a local server and prompts interactively, or pass `--url` to skip prompts):

```bash
civex db setup-postgres --url postgresql+psycopg2://user:pass@host:5432/dbname
```

## Quick start

```bash
# Define your data shape
civex schema create trial --description "A single experimental trial"
civex schema add-field trial subject --type string --required
civex schema add-field trial duration --type float
civex schema add-field trial result --type string --choices "pass,fail,inconclusive"

# Create a container for your data
civex collection create study-2024

# Add a record (civex will prompt for each field)
civex record add --to study-2024 --schema trial

# Query records
civex record find --in study-2024 --schema trial
```

## Start the web UI

The desktop app starts the server automatically. If you're using the CLI:

```bash
civex serve
```

Open [http://localhost:8000](http://localhost:8000). The UI lets you browse schemas, datasets, and records, upload files, run workflows, and monitor jobs — all without using the CLI.

!!! tip
    Use `civex serve --reload` during development for automatic restarts on code changes.
