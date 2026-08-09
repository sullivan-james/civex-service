# Remote sync

Civex can push and pull your project between machines using SSH or a shared filesystem. This lets you work locally and sync to a server, or collaborate with a colleague.

## How it works

Changes to records, schemas, and collections are tracked as they happen. `civex push` automatically groups any pending changes into a commit before transferring, so you never need a separate manual commit step. File objects are pushed before the database so the receiver can access them immediately.

Pull is fast-forward only — if the remote has commits you haven't pulled, civex refuses to push and asks you to pull first (similar to Git).

## Checking status

```bash
civex status
```

Shows changes not yet part of a pushed commit, and commits that exist locally but haven't been transferred to the remote.

## Configure a remote

```bash
# SSH remote
civex remote set ssh://user@hostname/path/to/project

# Local path (useful for network drives or testing)
civex remote set file:///mnt/shared/civex-project

# If civex is not on the remote's PATH (e.g. installed in a venv)
civex remote set ssh://user@hostname/path/to/project \
  --remote-civex ~/venv/bin/civex
```

```bash
civex remote show    # view the current remote
civex remote unset   # remove it
```

## Push and pull

```bash
civex push
```

```bash
civex pull
```

If the remote has commits you haven't pulled, `civex push` refuses and tells you to run `civex pull` first.

## Initial setup on the remote

The remote path must be an initialised civex project (a bare repository). Run on the remote machine:

```bash
civex init --bare /path/to/project
```

Or clone from an existing project:

```bash
civex clone ssh://user@hostname/path/to/source /path/to/destination
```

## What is transferred

- **Push:** all commits since the last push, plus all referenced file objects.
- **Pull:** all commits since the last pull, plus metadata about new file objects (bytes are fetched lazily on next access).

File objects are content-addressed — identical files are transferred once regardless of how many records reference them.
