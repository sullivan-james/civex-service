# Syncing between machines

A project can follow an **authority**: one civex that holds the project's shared
copy. Every other install (a *device*) sends its changes to the authority and
receives everyone else's. There is one authority per project, and devices never
talk to each other.

Everything works offline. Changes are recorded on the device first and go when the
authority can be reached.

## Set up the authority

The authority is an ordinary civex project, served by `civex serve`. On the
machine that will hold the shared copy:

=== "CLI"
    ```bash
    civex sync authority enable
    civex sync device add laptop     # prints the laptop's token, once
    civex serve --allow-remote
    ```

=== "Web UI"
    Settings → **Sync** → *Other devices following this project*: **Accept
    devices**, then **Issue a token** for each device. Copy the token straight
    away: it is shown only once. Then restart `civex serve` with `--allow-remote`.

Each device gets its own token. `civex sync device list` shows them, and
`civex sync device revoke <name>` stops one working (a lost laptop, say). The
devices already issued keep their tokens if you stop accepting devices.

On a project that serves, other machines can reach only the sync address
(`/api/sync/v1/`); the rest of the app stays local to that machine. Put the server
behind HTTPS (a reverse proxy) before exposing it, because the token is sent with
every request.

## Connect a device

=== "CLI"
    ```bash
    civex clone https://civex.example.com my-project --token <token>
    # or, in an existing project:
    civex sync connect https://civex.example.com --token <token>
    ```

=== "Web UI"
    Settings → **Sync**: the authority's address and the device token, then
    **Connect**.

What connecting does depends on what each side holds:

| This project | The authority | What happens |
| --- | --- | --- |
| Empty | Has data | This project **becomes a copy** of the authority. |
| Has data | Empty | This project **fills the authority**. |
| Has data | Has data | Refused: merging two projects is not supported. |
| The same project | | Picks up where it left off. |

A large project takes a while to copy, so both the CLI and Settings → Sync show
progress, and the copy carries on if the page is closed. A copy that stops halfway
(the network drops, the computer sleeps) is finished by connecting again;
**Try again** in Settings → Sync uses the token the device already has.

The project is ready to use as soon as its records have arrived. Two things follow
in the background:

- **Earlier history.** Activity fills in with the changes made before this device
  joined. `civex clone` shows this with a bar of its own; Ctrl+C leaves it to finish
  later.
- **Files.** See [Files](#files) below.

## Syncing by itself

While `civex serve` is running, the project syncs in the background: a few seconds
after you make changes, and every minute to bring in other people's. Without a
server, `civex sync watch` does the same in a terminal.

| To... | CLI | Web UI |
| --- | --- | --- |
| Sync now | `civex sync now` | **Sync now** (Settings → Sync, or the status bar) |
| See where it stands | `civex sync status` | Settings → Sync |
| Change how often | `civex sync interval 300` | Settings → Sync |
| Sync only when asked | `civex sync interval never` | Settings → Sync → *Never* |
| Stop and start | `civex sync pause` / `resume` | **Pause** / **Resume** |
| Stop following the authority | `civex sync disconnect` | **Disconnect** |

If the authority can't be reached, civex backs off (up to 15 minutes between tries)
and the status bar says why. A refusal that waiting can't fix, such as a revoked
token, says so and waits for you. Disconnecting leaves the data where it is.

## Files

Changes and files travel separately, so a file never holds a change up.

**Sending.** A device uploads the files its records use that the authority doesn't
have. If a file can't be read right now (its drive is unplugged), the change goes
without it. Every few minutes, and on every manual sync, civex checks again and
sends whatever it can now read. That covers plugging the drive back in, or adding
the same file again later (the same content is the same file).

**Receiving.** A file another device added reaches this computer in one of three
ways:

- **In the background**, for collections kept on this computer (see below).
  While civex runs, the files are downloaded a few at a time, with progress in
  the status bar and Settings → Sync.
- **When you open it.** Opening a file that isn't here yet downloads it first.
- **When you export.** An export, a zip or `civex files download` first downloads
  anything that isn't here, so what you get is complete. The preview downloads
  nothing, but says how many files will be downloaded, and the download shows
  in the status bar as part of the export.

Until then the file is marked **on the server**, and its chip says opening it will
download it. A file the authority hasn't got either (the device that added it
hasn't sent it yet) is tried again later, and opening it says so.

### Which files this computer keeps

Each collection either **keeps its files on this computer** (they're downloaded
in the background) or **fetches them when opened** (each file downloads the
first time it's opened or exported). The project has a default for this, and
each collection can override it, so the collections you work on stay local and
the rest only use space while you need them.

**Free up space** on a collection removes this computer's copies of its files.
Each file comes back the next time it's opened or exported. It's safe to use:

- It asks the server at that moment which files it holds, and removes only
  those. A file that was never sent stays.
- It never removes a file that a collection kept on this computer also uses.
- It counts first and says what goes and what stays, before anything is
  removed.
- It then sets the collection to fetch when opened, so the background download
  doesn't bring the files straight back.

=== "CLI"
    ```bash
    civex sync files                 # each collection: here, not here, its setting
    civex sync files opened          # the default: fetch when opened (or: all)
    civex sync keep "Humpbacks"      # keep this collection's files here
    civex sync keep "Archive" --opened   # or --reset to follow the default
    civex sync free "Archive"        # count, confirm, remove the copies
    civex sync fetch                 # download now everything kept here, with a bar
    ```

=== "Web UI"
    Settings → Storage → **Collections**: the default above the table, and for
    each collection its setting and **Free up space…**; its bar says how many
    files are not on this computer. To act on some files rather than a whole
    collection, use **Their files** above a collection's or record's list.

Downloaded files are checked against their content hash. They go on the drive their
collection's files go to (see
[Volumes and removable drives](files.md#volumes-and-removable-drives)), and a file already
stored is never stored twice.

## Who changes are recorded as

Changes you make are recorded under your computer's user name. To use another name
in a project, run `civex sync user "Dana"` or set it in Settings → Sync. It is saved
in the project's `_civex/config.toml` (`[identity]`), so each project has its own
and a copy of the folder carries it along. `civex sync user --reset` goes back to
your user name.

Once a change syncs, the authority records it under the name of the device that
sent it.

## What the authority accepts

The authority holds a change from a device to the same rules as an edit made on
the authority itself:

- **The fields' rules**: choices, limits, required values, unique keys and
  references.
- **Where a record sits**: a collection that lists the record's schema, and a
  parent, collection and schema that aren't deleted. An edit that meets a delete
  keeps the record. It is never revived into something deleted.
- **The schemas' rules**: name templates name fields that exist, and unique keys
  name the schema's own fields.

One action travels as one. Deleting a record deletes what is beneath it, and a
schema change can touch several fields. If such an action can't go in whole, none
of it goes in: the device is sent back the authority's state, and the review says
it was **not taken**.

## When changes collide

| What happened | Result |
| --- | --- |
| Two people edit **different fields** of a record | Both edits are kept. |
| Two people edit the **same field** | The authority's value stays. Yours is kept on your device, to review. |
| One edits a record another **deleted** | The record is kept, with an item to review. |
| One deletes a record another added something **beneath** | The record is kept. |
| A change the authority **refuses** | Kept on your device with the reason, to fix (see below). |
| Two people change a **schema** | Applied in the order the authority receives them. |

Nothing is lost in any of these. The value that didn't go in stays on the device
that made it until someone decides.

### Reviewing

Everything to review is settled on the **record's own page**, in its **Resolve**
tab. **Review** (in the status bar and Settings → Sync) lists what is waiting, with
a **Resolve** link per record. **Start review** steps through them record by
record, ticking each one off when it's settled.

**A clash** shows both sides like a version-control merge. The authority's value is
on the left and yours on the right, with the differences marked. The middle is the
record as it is now.

- **Accept theirs** or **Accept yours** settles one field. **Accept all theirs** or
  **Accept all yours** settles every clash on the record.
- Or edit the middle yourself, with the field's usual input. That settles the field
  too.
- If the value has changed again since, accepting yours says so and asks you to
  confirm.

**A refused record** isn't two sides to choose between, so it isn't shown as a
merge. You get the server's reason and the field it names, editable in place, with
what that field allows:

- **Fix the value and save.** That sends the record again, and the item closes as
  *Went in* once the authority takes it.
- **Send unchanged** sends it again as it is. This is useful when the cause was
  elsewhere, for example a parent that has since been restored. The item shows
  *Sending again…* until the authority answers. If the record is refused again,
  the same item says why.
- **Keep it on this device only** (for a new record) or **Let it go** (for a change)
  closes the item and sends nothing.

A record has one item however many times it was sent. A record made on one device
while another narrowed its field's choices is the usual case.

**An edit that met a delete** says who deleted the record and offers **Keep it** or
**Delete it**.

**Keep theirs for all** on the review page settles everything that's waiting the
authority's way. It counts first and says what goes (your parked values; your data
doesn't change), and **Undo** is there straight afterwards. In Activity, a change
that didn't go in as made carries a badge (*Clashed*, *Refused*, *Met a delete* or
*Not taken*), and its window shows how it ended.

From a terminal:

```bash
civex sync conflicts [--record <id>]                 # what is waiting
civex sync resolve <id> --take theirs|mine|delete|retry
civex sync resolve <id> --take value --value '"M"'   # put a value of your own
civex sync resolve --all --take theirs [--kind rejected|conflict|edit_vs_delete]
civex sync reopen <id>...                            # take back "theirs"
```

`--force` puts your value back even though it has changed again since. With `--all`,
anything that can't be settled that way, or fails its checks, stays open and is
listed. `--take retry` sends a refused change again and waits for the answer: it
says whether it went in.

## History

Every change is in Activity, on every device, with who made it. Edits are stored as
what changed (not the whole record each time), so history stays small.

A device that joins doesn't download all of the project's history before it can be
used. The history arrives afterwards, a little at a time, oldest first.

Projects from civex 1.2.0 and earlier stored a whole copy of the record with every
edit. They are converted after opening, in the background: the status bar shows
*Tidying history*, and nothing has to wait for it.

- Settings → Database → **History storage** shows how much room history takes and
  can give the room back to the disk.
- In the CLI, `civex history compact --vacuum` does the same.

## If the network fails

Every change carries its own id, so sending one twice (because a reply was lost)
changes nothing. The authority saves a change before it answers, so a device is
never told a change went in when it didn't. An authority that falls behind or
loses its history can't confuse a device: one that finds itself behind the
authority's history copies the project again.

## Moving to another server

Run `civex sync connect <new address> --token <token>` on each device.

- If the new authority is empty, the first device to connect fills it.
- The rest then follow it. Any item waiting for review against the old server is
  closed, since it was about that server.

## Moving a device

The token and device id live in `~/.civex/sync.toml`, not in the project folder.
Copying a project folder doesn't copy its identity: the copy has to be connected
with a token of its own.

## What doesn't sync

Schemas, fields, collections, saved views, records and their files sync. These
don't, and stay on each computer:

- Saved exports (export definitions) and workflows.
- Settings in `config.toml`: storage volumes, retention, the map, automation.
- Workflow runs and their logs.
- Pins and recent items, which are kept by each browser.
