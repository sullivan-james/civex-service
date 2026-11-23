# Syncing between machines

One civex, the **authority**, holds a project's shared copy. Every other copy, a
**device**, sends its changes there and receives everyone else's. Devices never
talk to each other, and everything works offline: changes are recorded locally
and go when the authority can be reached.

To set it up, follow [Sync a project between computers](../how-to/set-up-sync.md).
This page is how it behaves.

## Connecting

```bash
# on the authority
civex sync authority enable
civex sync device invite laptop
civex serve --sync-only            # behind HTTPS

# on a device
civex clone https://lab-pc.tail1234.ts.net my-project --invite civex_inv_…
civex sync connect https://… --invite civex_inv_…   # an existing project
```

| This project | The authority | Connecting… |
|---|---|---|
| Empty | Has data | makes this a copy of it |
| Has data | Empty | fills the authority |
| Has data | Has data | is refused: two projects can't be merged |
| The same project | | picks up where it left off |

- **Invites** work once, for 24 hours (`--hours`), and are shown once. They start
  with `civex_inv_`, so secret scanners catch one pasted by mistake.
- **Or ask to join.** Connect without an invite and the device shows a code
  (`ABCD-2345`) and waits. On the authority, `civex sync device approve
  ABCD-2345 laptop` (or Settings → Sync → *Asking to join*) lets it in by name,
  `civex sync device deny` turns it away, and a code nobody approves in 15
  minutes lapses. The device is then a device like any invited one. When the
  server has a page for it (the hub does), the device shows that address with
  the code instead: open it and enter the code. `civex clone <address>` does
  the same without `--invite`, and `civex auth status` shows this device's
  name, id, whether it has joined, and the last sync error.
- **Keys:** joining makes the device a key pair. It then signs in with its key for
  short sessions, and checks the authority's key, so a different server at the
  same address gets nothing. `civex sync device revoke <name>` stops a device at
  once.
- **HTTPS or SSH only.** Devices refuse `http://` except to this computer. Use
  [Tailscale](../how-to/set-up-sync.md), or bind `civex serve --sync-only` to
  `127.0.0.1` behind a reverse proxy (Caddy, nginx). `--sync-only` serves only
  `/api/sync/v1/`. Never put the full app on a network: it has no sign-in. On a
  machine you can SSH into, an `ssh://` address needs no server running at all
  ([Over SSH instead](../how-to/set-up-sync.md#over-ssh-instead)).
- **A server or a device, not both.** A project that serves devices can't
  connect to another server, and one that follows a server can't serve devices:
  civex refuses either. To make the old server follow a new one (moving
  servers), stop it serving first (Settings → Sync, or `civex sync authority
  disable`) and connect its devices to the new one. A project set up both ways
  by hand doesn't sync until one is turned off, and says so.
- **Big projects** show progress while copying, and an interrupted copy finishes
  when you connect again. Records arrive first. History and files follow in
  the background.

## When it syncs

While `civex serve` runs, a few seconds after each change and every minute.
Without the app, `civex sync watch` does the same in a terminal.

| To… | CLI | App (Settings → Sync) |
|---|---|---|
| Sync now | `civex sync now` | **Sync now** (also in the status bar) |
| See where it stands | `civex sync status` | the page itself |
| Change how often | `civex sync interval 300` | interval |
| Only when asked | `civex sync interval never` | *Never* |
| Pause / resume | `civex sync pause` / `resume` | **Pause** / **Resume** |
| Stop following | `civex sync disconnect` | **Disconnect** (keeps the data) |

An unreachable authority is retried with back-off (up to 15 minutes). A refusal
that waiting can't fix, such as a revoked device, says so and waits for you.

## Files

Changes and files travel separately. A sync moves records only, so it takes
seconds however large the files are, and a missing file never holds up a change.
Files move in the background, on their own, beside syncing.

- **Sending:** a device uploads files its records use that the authority lacks,
  with their own progress in the status bar: how many files and how much in
  all (`120 MB of 2.1 GB`), how fast, and how long is left, on one bar from
  the first file to the last. A file on an unplugged drive is
  sent once it can be read. Until the server has a file, its chip says **not on
  the server yet** (other computers can't open it), and the status bar counts
  such files and says why they haven't gone: going up in the background, on a
  drive that can't be read, or not on this computer at all (a computer that has
  them must send them). **Send now** (`civex sync send` from the command line)
  sends at once; `civex sync now` syncs records only and says how many files are
  still to go. civex remembers which files the server has said it holds and asks
  only about the rest; every few minutes, on **Send now** and on every manual
  sync it asks about all of them again.
- **Receiving:** a file another device added arrives in the background (for
  collections this computer keeps), when you open it, or before an export. Until
  then it is marked **on the server**.
- **Straight to storage:** an authority whose files are in a bucket (see
  [Storage volumes](storage.md#files-in-a-bucket-instead)) offers `direct_files`:
  a device asks it where to put a file and sends the bytes to the bucket itself,
  then tells the authority it is done; downloads are a redirect to the bucket.
  The authority only says where and records what arrived. An older device, or an
  authority with its files on drives, streams them as before.

### Which files a computer keeps

Each collection either **keeps its files here** (downloaded in the background)
or **fetches them when opened**. The project has a default and each collection
can override it.

```bash
civex sync files                       # per collection: here, not here, setting
civex sync files opened                # default for the project (or: all)
civex sync keep survey-2024              # keep this one here
civex sync keep archive-2019 --opened  # or --reset to follow the default
civex sync free archive-2019           # remove local copies
civex sync fetch                       # download everything kept, now
```

```text
Collection   Keeps                 On this computer  Not on this computer
survey-2024   every file (default)           0 (0 B)                     2
```

**Free up space** removes only copies the server confirms it holds, never one a
kept collection also uses, counts first, and then sets the collection to *fetch
when opened* so the files don't come straight back. In the app: Settings →
Storage → **Collections**.

## Conflicts

| What happened | Result |
|---|---|
| Two edits to **different fields** of a record | Both go in |
| Two edits to the **same field** | The authority's value stays; yours waits on your device for review |
| An edit to a record someone **deleted** | The record is kept, with an item to review |
| A delete of a record someone added something **beneath** | The record is kept |
| A change the authority **refuses** | Kept on your device with the reason |
| Two **schema** changes | Applied in the order the authority receives them |

Nothing is lost: a value that didn't go in stays on the device that made it until
someone decides.

**Reviewing in the app.** The status bar says when something waits. **Review**
lists it, and each record's **Resolve** tab settles it:

- **A clash** shows the authority's value on the left and yours on the right,
  differences marked. **Accept theirs**, **Accept yours**, or edit the middle.
- **A refused record** shows the reason and the field it names, editable in
  place. Fix it and save to send it again, **Send unchanged**, or **Let it go**.
- **An edit that met a delete** offers **Keep it** or **Delete it**.

**Keep theirs for all** on the review page settles everything the authority's
way, after counting, with **Undo**. In Activity, a change that didn't go in as
made is badged *Clashed*, *Refused*, *Met a delete* or *Not taken*.

**In a terminal:**

```bash
civex sync conflicts [--record <id>]
civex sync resolve <conflict id> --take theirs|mine|delete|retry
civex sync resolve <conflict id> --take value --value '"M"'
civex sync resolve --all --take theirs [--kind rejected|conflict|edit_vs_delete]
civex sync reopen <conflict id>...       # take back a "theirs"
```

`--force` puts your value back even if it changed again since.

## What the authority enforces

A change from a device must pass the same rules as an edit on the authority:
field rules (choices, limits, required, unique keys, references), where the
record sits (its collection lists its schema; its parent, collection and schema
aren't deleted), and schema rules (templates and unique keys name real fields).

An action travels whole. Deleting a record takes what's beneath it, and a schema
change can touch several fields. If it can't go in whole, none of it does, and
the device is sent back the authority's state, marked **not taken**.

## Who may change what

A project in a folder is yours: everything is allowed. A hosted civex knows who
is signed in and what they may do (`GET /api/me`: read, write records, change
the structure, add or delete files, notes, shared views, delete, manage members
and devices, each everywhere or in named collections), and holds a person's
device to the same rule as their browser: a change a device pushes that its
person may not make is refused like any change that breaks a rule, and the app
shows the control switched off, saying why.

### A device that may not read everything

When its person may not read some collections, their device holds a **partial
copy**: it simply never has those collections. The authority leaves them out of
everything it sends that device (the feed, the copy a joining device reads, the
counts it reports, and the files only they use), so no record, note, id or count
of a hidden collection reaches it. A change that would put something in a
collection the device may not read, or point at a record in one, is refused (the
change is marked **not taken**, as any refused change), and so is one that names a
collection it may write to for a record the authority holds in one it may not.
A record moved out of sight is removed from such a device (it is never told
where it went); one moved into sight is sent whole.

If the person is **given more** later, the device asks for it by itself: the
authority says which collections the device may read (sync protocol 5), and the
device reads the ones it did not have as they are now, then carries on with the
feed. That includes a record that moved out of a collection it could not read
into one it can, while it was away: such a record is read too (`snapshot` with
`dataset` and `left_after`), so the feed's later changes to it apply. A device that
was never told what it could read (it synced on an older protocol) reads any
collection it lacks the first time it is.

A device whose person may not read everything needs **protocol 5**: on an older
one the authority answers 426 ("update civex on this device"), because it could not
be told how far the authority looked or of a collection it is given. A device whose
person reads everything works on any supported protocol.

History stored by an older civex carries the collection a device *claimed*, not where
the authority had the record. The upgrade records the feed number it happened at
(`sync_meta.placed_from`, no rewrite of history); a limited device is sent an entry
from before it only while its record is still somewhere that device may read, so a
stale claim cannot carry a value out of a collection. Fetching history before joining
remembers how far it looked (`sync_meta.history_scan`), so it can be done in steps.
Values written while a record was hidden, before the upgrade, can reach a device once
the record is visible again (a record carries its earlier history with it, as in
`hosting.md`); after the upgrade the feed sends such a record only as a whole creation,
and a note is placed only by changes made since the upgrade.

A hidden stretch of the feed is looked past in bounded steps: one request reads at
most 2,000 entries, and when nothing in them is for the device it answers an empty
page with `more` and `through`, and the device asks again from there.

If the person is **given less**, the authority stops sending, and that is all it
can do: **what the device already holds cannot be taken back.** The records it
copied stay on that computer, and its person can read them there. A copy made
again from the authority (an authority that pruned its history does this) drops
what the device may no longer read. A host that needs a person never to keep
data it once showed them should not give it to a device at all.
Hidden collections' ids can still appear in shared things that are project-wide:
the Analytics page, and the number of changes (gaps in feed numbers).

## Who a change is recorded as

Your changes carry your OS user name, or the name set with
`civex sync user "Dana"` (saved in the project's `config.toml`;
`--reset` to undo). The authority also records which device sent each change,
and Activity shows both ("Dana via laptop"). A device key proves the device, not
the person.

## Sharing workflows and plugins

Workflows and plugins don't sync. A plugin is code, so they are shared on purpose
through the authority's **library**: one person publishes, another installs.

```bash
civex sync library list                            # what's shared and how it stands here
civex sync library publish workflow tidy           # with the plugins it uses
civex sync library show plugin my_step -v 2        # read a version first
civex sync library install workflow tidy           # asks before writing anything
civex sync library install plugin my_step -v 1     # roll back
civex sync library remove workflow tidy -v 1
```

- **Nothing arrives by itself.** Published text is kept in the authority's
  database and written into `_civex/` only when someone installs it, after
  showing every file, its version and hash, and (for a plugin) its code.
- **The authority checks without running:** safe names, 256 KB at most, valid
  YAML with no aliases, valid Python defining `Plugin`, no built-in ids.
- **Versions:** each changed publish is the next version, and all are kept. A
  workflow pins the plugin versions it was published with. Before installing a
  new plugin version, civex checks every workflow here that uses it, and installs
  nothing that would break one unless you choose **Install anyway**. For a
  breaking change, publish a new plugin (new id) instead.
- **Who may publish:** the authority's own computer always may. A device may
  once allowed (`civex sync device allow-publish laptop`), within
  `civex sync authority library off|workflows|all` (default `workflows`).
- Changes that arrive by sync never start a workflow.

In the app, the **Workflows** page lists the library beside your own workflows
with a **Sharing** column, and each workflow's **Sharing** tab has its versions.

## History

Every device has the full history in Activity. A new device downloads it after
joining, a little at a time. Edits are stored as what changed, so history stays
small. Projects from civex 1.2.0 and earlier are converted in the background
after opening (*Tidying history* in the status bar). Reclaim the space with
Settings → Database → **History storage** or `civex history compact --vacuum`.

## Reliability

- Each change has an id, so sending one twice changes nothing.
- The authority saves a change before answering, so a device is never told
  "done" for a change that wasn't saved.
- A device finding itself ahead of an authority's history copies the project
  again.

## Upgrading

Devices and the authority agree on the newest sync protocol both speak. When a
release changes it (the changelog says "sync protocol N"), **update the authority
first**, then the devices. A device that can't sync says which side to update.

## Moving

- **A new authority:** run `civex sync connect <new address> --invite …` on each
  device. If the old authority is to follow the new one, stop it serving
  first. If the new one is empty, the first device fills it. Review items about
  the old server are closed.
- **A device to a new computer:** its id and key live in `~/.civex/sync.toml`,
  not in the project, so a copied folder isn't the same device. Connect the copy
  with a new invite.

## What doesn't sync

Schemas, fields, collections, saved views, the Analytics page, records, the
notes left on them and their files sync. These
stay on each computer:

- saved exports, and workflows and plugins (use the library);
- `config.toml` settings: volumes, retention, the map, automation;
- workflow runs and their logs;
- pins and recent items (kept by each browser).
