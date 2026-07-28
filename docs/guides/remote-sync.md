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

## CivexHub

CivexHub is a self-hosted server that stores civex repositories centrally and lets multiple clients push and pull data over SSH. Unlike the bare-repository setup above, no repository needs to be pre-created on the hub — the first `civex push` to a given `owner/repo` path creates it on contact.

### Server setup

CivexHub's Docker image includes OpenSSH. SSH is configured automatically: no manual `sshd_config` editing is required.

**How it works under the hood:**

- `sshd` is started alongside the civexhub HTTP process inside the container.
- Every incoming SSH connection is forced through `civexhub-shell`, a thin command dispatcher that reads `SSH_ORIGINAL_COMMAND` and routes it to transfer-pack, receive-pack, or object fetch/put.
- Host keys are generated on first boot (`ssh-keygen -A`) and survive restarts as long as the container is not recreated.
- Authentication is public-key only — password auth is disabled. `sshd` looks up authorised keys by calling `civexhub-keys <username>`, which queries the hub's database and prints the keys in `authorized_keys` format with the forced-command prefix already applied.

**Start the hub with Docker Compose:**

```bash
cd civex-hub
docker compose up -d --build
```

This exposes:

- `8001` — HTTPS API and web UI
- `2222` — SSH (use `2222` on the host to avoid conflicting with any SSH daemon already running on the host)

### Adding SSH keys

SSH keys are managed through the hub web UI or API. There is no server-side key file to edit.

=== "Web UI"

    1. Open `http://localhost:8001` and log in.
    2. Go to **Settings → SSH keys**.
    3. Paste your public key (`~/.ssh/id_ed25519.pub` or similar) and give it a title.
    4. Click **Add key**.

=== "API"

    ```bash
    # 1. Get a token
    TOKEN=$(curl -s -X POST http://localhost:8001/api/v1/auth/token \
      -H "Content-Type: application/json" \
      -d '{"username":"alice","password":"secret"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

    # 2. Upload your public key
    curl -s -X POST http://localhost:8001/api/v1/settings/ssh-keys \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"my-laptop\",\"public_key\":\"$(cat ~/.ssh/id_ed25519.pub)\"}"
    ```

Keys can be listed and deleted via the same UI or via `GET`/`DELETE /api/v1/settings/ssh-keys`.

### SSH host key verification

The first time you push to a hub over SSH, your SSH client will ask you to verify the host key:

```
The authenticity of host '[localhost]:2222 ([127.0.0.1]:2222)' can't be established.
ED25519 key fingerprint is SHA256:...
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

Type `yes` to add it to `~/.ssh/known_hosts`. Subsequent pushes and pulls will connect silently. In CI or scripting contexts, add `StrictHostKeyChecking=no` in `~/.ssh/config` for the hub host.

## What is transferred

- **Push:** all commits since the last push, plus all referenced file objects.
- **Pull:** all commits since the last pull, plus metadata about new file objects (bytes are fetched lazily on next access).

File objects are content-addressed — identical files are transferred once regardless of how many records reference them.
