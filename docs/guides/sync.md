# Syncing between machines

A project can follow an **authority**: one civex that holds the project's shared
copy. Every other install (a *device*) sends its changes to it and receives
everyone else's. There is one authority per project; devices never talk to each
other.

## Set up the authority

On the machine that will hold the shared copy:

```bash
civex sync authority enable
civex sync device add laptop     # prints a token, once
civex serve --allow-remote
```

Only the sync address (`/api/sync/v1/`) is reachable from other machines on a
project set to serve; the rest of the app stays local to that machine. Put the
server behind HTTPS (a reverse proxy) before exposing it: the token is sent in
every request.

## Connect a device

```bash
civex clone https://civex.example.com my-project --token <token>
# or, in an existing project:
civex sync connect https://civex.example.com --token <token>
```

- A new or empty project **becomes a copy** of the authority.
- A project with data **fills an empty authority**.
- Two projects that both hold data are refused: merging them is not supported.

Run `civex sync` to sync now, `civex sync status` to see where things stand,
`civex sync pause` / `resume` to stop and start it.

## Syncing by itself

While `civex serve` is running, the project syncs in the background: a few
seconds after you make changes, and every minute (Settings → Sync changes the
interval) to bring in other people's. If the authority can't be reached it backs
off, up to 15 minutes between tries, and the status bar says why. Without a
server, `civex sync watch` does the same in a terminal.

Settings → **Sync** is where you connect, see when it last synced, press
**Sync now**, pause the schedule, disconnect, and settle conflicts.

Set the frequency to **Never** (Settings → Sync, or `civex sync interval never`)
to sync only when you press **Sync now** (also in the top bar) or run
`civex sync`.

Changes and files travel separately, so a missing file never holds a change up.
If a change cites a file this computer can't read right now (a drive that is
unplugged, or files you still have to recover), the change is sent and the file
is remembered as *owed*. Settings → Sync shows how many; they are uploaded by
themselves as soon as they can be read, whether you plug the drive back in or
add the same files later (matching content has the same hash). The server log
has one line per sync, and a warning for anything refused or in conflict.

## Who changes are recorded as

Changes you make are recorded under your computer's user name. To use another
name for a project: `civex sync user "Dana"` or Settings → Sync (kept for you on
this computer, not in the project). `civex sync user --reset` goes back.

## What happens when changes collide

- Two people edit **different fields** of a record: both edits are kept.
- Two people edit the **same field**: the authority's value stays, and yours is
  kept as a conflict. `civex sync conflicts` lists them; `civex sync resolve <id>
  --take mine|theirs` settles one (`mine` makes your value a new change).
- One edits a record another **deleted**: the record is kept, with a conflict.
- Schema changes are applied in the order the authority receives them.

## If the network fails

Changes are recorded locally first and sent when the authority can be reached. A
change carries its own id, so sending it twice (a reply was lost) changes
nothing. Files are sent before the changes that refer to them, and a change
waits until its files have arrived.

## Moving a device

The token and device id live in `~/.civex/sync.toml`, not in the project folder,
so copying a project does not copy its identity. Revoke a lost device with
`civex sync device revoke <name>`.
