from __future__ import annotations

import shlex
import sys


def run_shell() -> None:
    from civex.main import app

    sys.stdout.write("civex shell  —  type 'help' or 'exit'\r\n")
    sys.stdout.flush()

    while True:
        sys.stdout.write("civex> ")
        sys.stdout.flush()

        try:
            line = sys.stdin.readline()
        except (EOFError, KeyboardInterrupt):
            sys.stdout.write("\r\n")
            sys.stdout.flush()
            break

        if not line:
            break

        line = line.strip()
        if not line:
            continue
        if line in ("exit", "quit", "q"):
            sys.stdout.write("Goodbye.\r\n")
            sys.stdout.flush()
            break

        try:
            args = shlex.split(line)
        except ValueError as e:
            sys.stdout.write(f"Parse error: {e}\r\n")
            sys.stdout.flush()
            continue

        if args and args[-1].lower() == "help":
            args[-1] = "--help"

        try:
            app(args, standalone_mode=True)
        except SystemExit:
            pass
        except Exception as e:
            sys.stdout.write(f"Error: {e}\r\n")

        sys.stdout.flush()


if __name__ == "__main__":
    run_shell()
