# Install

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

    Download the latest release wheel and install it:

    ```bash
    gh release download --repo CivexData/civex-service --pattern "*.whl"
    pipx install "./$(ls civex-*-py3-none-any.whl)[server]"
    ```

    The version in the wheel's filename is derived from the git tag it was built from, so it changes with every release — the commands above pick up whatever was just downloaded instead of pinning a specific version.

    To upgrade, re-run `pipx install --force` with the newly downloaded wheel.

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

## Next step

[Create your first project →](first-project.md)
