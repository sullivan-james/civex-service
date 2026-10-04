# Install

civex is published on PyPI as [`civex`](https://pypi.org/project/civex/) and requires Python 3.12 or newer.

=== "pipx (recommended)"

    ```bash
    pip install pipx
    pipx ensurepath        # adds civex to PATH — open a new terminal after this
    ```

    ```bash
    pipx install civex
    ```

=== "pip"

    If you'd rather manage the virtual environment yourself:

    ```bash
    python -m venv venv && source venv/bin/activate
    pip install civex
    ```

Everything is included: the HTTP API and web UI, workflow execution, the
PostgreSQL driver, AI-assisted commands and telemetry. There's nothing to
choose. (`civex[server]` and the other old extra names still install fine —
they're now no-ops — so existing scripts and installs keep working.)

The one optional extra is the desktop tray app, which pulls in
platform-specific GUI packages:

```bash
pipx install "civex[desktop]"
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
