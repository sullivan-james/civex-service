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
- **Keys:** joining makes the device a key pair. It then signs in with its key for
  short sessions, and checks the authority's key, so a different server at the
  same address gets nothing. `civex sync device revoke <name>` stops a device at
  once.
- **HTTPS only.** Devices refuse `http://` except to this computer. Use
  [Tailscale](../how-to/set-up-sync.md), or bind `civex serve --sync-only` to
  `127.0.0.1` behind a reverse proxy (Caddy, nginx). `--sync-only` serves only
  `/api/sync/v1/`. Never put the full app on a network: it has no sign-in.
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

Changes and files travel separately, so a missing file never holds up a change.

- **Sending:** a device uploads files its records use that the authority lacks.
  A file on an unplugged drive is sent once it can be read. civex checks every
  few minutes and on every manual sync.
- **Receiving:** a file another device added arrives in the background (for
  collections this computer keeps), when you open it, or before an export. Until
  then it is marked **on the server**.

### Which files a computer keeps

Each collection either **keeps its files here** (downloaded in the background)
or **fetches them when opened**. The project has a default and each collection
can override it.

```bash
civex sync files                       # per collection: here, not here, setting
civex sync files opened                # default for the project (or: all)
civex sync keep humpbacks              # keep this one here
civex sync keep archive-2019 --opened  # or --reset to follow the default
civex sync free archive-2019           # remove local copies
civex sync fetch                       # download everything kept, now
```

```text
Collection  Keeps                 On this computer  Not on this computer
humpbacks   every file (default)           0 (0 B)                     2
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
  device. If the new one is empty, the first device fills it. Review items about
  the old server are closed.
- **A device to a new computer:** its id and key live in `~/.civex/sync.toml`,
  not in the project, so a copied folder isn't the same device. Connect the copy
  with a new invite.

## What doesn't sync

Schemas, fields, collections, saved views, records and their files sync. These
stay on each computer:

- saved exports, and workflows and plugins (use the library);
- `config.toml` settings: volumes, retention, the map, automation;
- workflow runs and their logs;
- pins and recent items (kept by each browser).
