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
unplugged, or files you still have to recover), the change is sent without it. Every
few minutes (and on every manual sync) civex checks which files the authority
lacks that it can now read and uploads them, whether you plug the drive back in or
add the same files later (matching content has the same hash). The server log
has one line per sync, and a warning for anything refused or in conflict.

## Who changes are recorded as

Changes you make are recorded under your computer's user name. To use another
name in a project: `civex sync user "Dana"` or
Settings → Sync. It is saved in that project's `_civex/config.toml` (`[identity]`),
so each project has its own, and a copy of the folder carries it along.
`civex sync user --reset` goes back. Once changes sync, the authority records
them under the device's name.

## What happens when changes collide

- Two people edit **different fields** of a record: both edits are kept.
- Two people edit the **same field**: the authority's value stays, and yours is
  kept as a conflict on your device. Nothing is lost either way.
- One edits a record another **deleted**: the record is kept, with a conflict.
- A change the authority **refuses** (a value outside its field's rules, a name
  already taken, a unique key that is already used) is kept on your device with the
  reason. The authority holds changes from a device to the same rules as an edit
  made there.
- Schema changes are applied in the order the authority receives them.

### Reviewing conflicts

Settling happens on the **record's own page**, in a side-by-side view like a
version-control merge. **Review** (the status bar, or Settings → Sync) is the inbox
that gets you there: every change that did not go in as made, which record it was,
and a **Resolve** link on each row; **Start review** takes you through them record
by record.

On a record with something to settle, a **Resolve** tab opens the merge view:

- **Left** is the other side (what the authority kept), **right** is yours, and the
  **middle** is what the record is now. Words, list items and values that differ are
  marked on each side, and what it was before either of you changed it is shown
  above.
- **Accept theirs** / **Accept yours** settles one field; **Accept all theirs** /
  **Accept all yours** settles every clash on the record. Or click the result and
  set the value yourself, with the field's usual input: that settles it too.
- A change the authority **refused** has its own block with the reason, what each
  field was before and what you set it to, and **Send again** once you have fixed
  the values in the middle. An edit that met a **delete** says who deleted the record
  and offers **Keep it** or **Delete it**; either way nothing was lost to get here.
  A delete that met an **edit** shows what the other side changed.
- Rows you settle stay on screen, marked, until you leave: **Undo** takes back
  *Keep theirs*.
- While you review, a **stepper** at the top of each record page shows every record
  you are going through (ticked once settled), with **Next** to the next one still to
  do. **Exit review** ends it.

The **Fields** tab marks the fields that clashed, and a banner there takes you to
the merge view.

The review page narrows by kind (**Show**), settles ticked rows, and has **Keep
theirs for all**: it counts first and says what goes (your parked values; your data
doesn't change), and **Undo** is there straight afterwards.

In **Activity**, a change that did not go in as made carries a badge (*Clashed*,
*Refused*, *Met a delete*, or *Sync: settled*), and its window shows both sides the
same way, how it ended, and a link to settle it while it is open.

Each is settled with one of these (the merge view words the first two *Accept
theirs* and *Accept yours*):

| Choice | What it does |
| --- | --- |
| **Keep theirs** | Nothing to change: this project already has the authority's value. |
| **Use mine** | Puts your value back as a new edit. It is checked like any edit, appears in the history, and syncs. If the value has changed again since, you are told what it is now and asked to confirm. |
| **Edit…** | Puts a value you type instead (text and number fields). |
| **Delete it** | For a record deleted elsewhere: deletes it here too. |
| **Send again** | For a refused change: sends it again from the record as it is now, after you have put the cause right. |

Nobody else is told when you put your value back; it shows in Activity with your
name, like any change.

From a terminal, `civex sync conflicts` lists them and `civex sync resolve <id>
--take theirs|mine|delete|retry` settles one (`--force` puts yours back even though
the value has changed again). `civex sync resolve --all --take theirs` settles every
open one, `--kind rejected` (or `conflict`, `edit_vs_delete`) only that kind; those
that can't be settled that way, or fail their checks, stay open and are listed.

## If the network fails

Changes are recorded locally first and sent when the authority can be reached. A
change carries its own id, so sending it twice (a reply was lost) changes
nothing. Files are sent before the changes that refer to them, and a change
waits until its files have arrived.

## Moving a device

The token and device id live in `~/.civex/sync.toml`, not in the project folder,
so copying a project does not copy its identity. Revoke a lost device with
`civex sync device revoke <name>`.
