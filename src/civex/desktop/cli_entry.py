"""Thin entry point for the CLI executable produced by PyInstaller."""
from civex.main import app

if __name__ == "__main__":
    app(prog_name="civex")
