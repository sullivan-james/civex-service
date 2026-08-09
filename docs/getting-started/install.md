# Install

civex is published on PyPI as [`civex`](https://pypi.org/project/civex/) and requires Python 3.12 or newer.

=== "pipx (recommended)"

    ```bash
    pip install pipx
    pipx ensurepath        # adds civex to PATH — open a new terminal after this
    ```

    ```bash
    pipx install "civex[server]"
    ```

    The `server` extra pulls in the HTTP API and web UI. Extras can be combined:

    | Extra | Adds |
    |---|---|
    | `server` | HTTP API and web UI (`civex serve`) |
    | `workflows` | Workflow execution and the built-in plugins |
    | `postgres` | PostgreSQL driver |
    | `ai` | AI-assisted commands |
    | `telemetry` | Logging and metrics exporters |

    ```bash
    pipx install "civex[server,workflows,postgres]"
    ```

    To upgrade:

    ```bash
    pipx upgrade civex
    ```

=== "pip"

    If you'd rather manage the virtual environment yourself:

    ```bash
    python -m venv venv && source venv/bin/activate
    pip install "civex[server]"
    ```

Verify the install:

```bash
civex --version
civex --help
```

## Next step

[Create your first project →](first-project.md)
