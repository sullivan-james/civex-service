# Plumbing commands

These are **plumbing, not porcelain**: internal commands invoked machine-to-machine by `SSHTransport` when `civex push`, `civex pull`, or `civex clone` talk to a remote over SSH. They are declared `hidden=True` in the CLI and do not appear in `civex --help`. They are not a supported user interface — if you want to sync a project, see [Remote sync](../../guides/remote-sync.md) instead.

## The five commands

| Command | Args | Purpose |
|---|---|---|
| `transfer-pack` | `BARE_PATH`, `--since-seq` | Export commits after `--since-seq` from the bare repo to stdout as a JSON bundle |
| `receive-pack` | `BARE_PATH` | Apply a JSON bundle read from stdin to the bare repo |
| `head-seq` | `BARE_PATH` | Print the bare repo's maximum commit sequence number |
| `get-object` | `BARE_PATH`, `SHA256` | Write a stored file object's bytes to stdout |
| `put-object` | `BARE_PATH`, `SHA256` | Read bytes from stdin and store them as a file object |

`BARE_PATH` must point at an initialised bare repository (a directory containing a `CIVEX_BARE` marker); all five commands fail if it doesn't.

## When you'd see these

- Configuring an SSH `authorized_keys` forced-command restriction that dispatches to one of these commands based on `SSH_ORIGINAL_COMMAND`.
- Debugging a failed `push`/`pull`/`clone` — the SSH client invokes these on the remote, so their stderr shows up in the transport error.
- Reading server-side SSH or process logs, where the invoked command line will name one of these instead of a porcelain command.

## Stability

These are an internal wire protocol between `SSHTransport` and the remote `civex` binary, not a public interface. Their arguments, stdin/stdout framing, and behavior may change without a deprecation cycle — do not script against them directly.
