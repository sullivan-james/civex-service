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
    civex sync device invite laptop  # prints the laptop's invite, once
    civex serve --sync-only          # what devices reach, behind HTTPS
    ```

=== "Web UI"
    Settings → **Sync** → *Other devices following this project*: **Accept
    devices**, then **Invite** each device by name. Copy the invite straight
    away: it is shown only once. Then start `civex serve --sync-only` for the
    devices.

An invite works **once**, for 24 hours (`--hours` to change it). The device joins
with it and makes a key of its own; from then on it signs in with that key, which
never leaves it, for a session that lasts a few minutes. Nothing a device sends
can be reused for long, and a server that isn't the one it joined is refused
before anything is sent to it.

`civex sync device list` shows the devices with their keys' short codes and the
invites waiting; `civex sync device cancel <name>` cancels an invite and
`civex sync device revoke <name>` stops a device at once (a lost laptop, say). An
invite starts with `civex_inv_`, so secret scanners recognise one pasted by
mistake.

`civex serve --sync-only` serves the sync address (`/api/sync/v1/`) and nothing
else. Devices only connect over `https://`, because invites and sessions travel in
requests, so it needs an HTTPS address in front of it:

- **On your own network, or across several:** [Syncing with Tailscale](#syncing-with-tailscale)
  below is the simplest, with nothing to configure on the civex side.
- **On a server you run:** bind it to `127.0.0.1` and put an HTTPS reverse proxy
  (Caddy, nginx) with a certificate in front.

A plain `http://` address on your network (`http://192.168.1.20:8000`) doesn't
work: a device refuses it. Run the app itself (`civex serve`, without the flag) on
the same machine for yourself, and reach it from elsewhere over SSH
(`ssh -L 8000:localhost:8000 <server>`).

## Connect a device

=== "CLI"
    ```bash
    civex clone https://civex.example.com my-project --invite <invite>
    # or, in an existing project:
    civex sync connect https://civex.example.com --invite <invite>
    ```

=== "Web UI"
    Settings → **Sync**: the authority's address and the invite, then
    **Connect**.

The address must be `https://`; `http://` is accepted only for this computer.

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
**Try again** in Settings → Sync needs no invite: the device has joined.

The project is ready to use as soon as its records have arrived. Two things follow
in the background:

- **Earlier history.** Activity fills in with the changes made before this device
  joined. `civex clone` shows this with a bar of its own; Ctrl+C leaves it to finish
  later.
- **Files.** See [Files](#files) below.

## Syncing with Tailscale

[Tailscale](https://tailscale.com) puts your computers on a private network of their
own, wherever they are (one office, home, a laptop on the road), and gives each an
`https://` address with a real certificate. Only computers you add can reach it. It is
free for personal use and small teams.

**Once, for everyone**

1. [Install Tailscale](https://tailscale.com/download) on the authority and on every
   device, and sign each in to the same Tailscale account (your *tailnet*).
2. In the Tailscale admin console, under **DNS**, turn on **MagicDNS** and **HTTPS
   Certificates**. (`tailscale serve` below asks for this, with a link, if it is
   off.)

**On the authority**

```bash
civex sync authority enable
civex sync device invite laptop        # prints the laptop's invite: copy it now
civex serve --sync-only --port 8100    # leave this running
```

Then, in a second terminal:

```bash
tailscale serve --bg 8100
```

It prints the authority's address, such as `https://lab-pc.tail1234.ts.net`
(`tailscale serve status` shows it again later). The first visit can take a few
seconds while Tailscale fetches the certificate.

To use civex yourself on this computer at the same time, run `civex serve` as usual:
it uses port 8000, the sync server 8100.

**On each device**

```bash
civex clone https://lab-pc.tail1234.ts.net my-project --invite <invite>
```

Or, in the app: Settings → **Sync**, the address and the invite, then **Connect**.

**Good to know**

- **Keep the sync server running.** Devices sync whenever `civex serve --sync-only`
  is up on the authority; while it isn't, they keep working and catch up later.
  `tailscale serve --bg` comes back by itself after a restart; start civex with the
  computer too (a login item on macOS, Task Scheduler on Windows, a systemd service on
  Linux).
- **Use `serve`, never `funnel`.** `tailscale funnel` puts an address on the public
  internet; `serve` keeps it inside your tailnet.
- **Point Tailscale at the sync server only** (port 8100 here), never at the app's
  port (8000): the app has no sign-in, so everyone in your tailnet could use it.
  Open the app on the authority itself, or from elsewhere over SSH as above.
- **Invite another device** with `civex sync device invite <name>`, or Settings →
  Sync → *Other devices following this project*.

## Syncing over SSH

If you can SSH into a machine (a university lab machine, a server at work), it can
hold the authority with nothing running there between syncs, the way a git remote
works. A device's `ssh://` address starts civex on that machine over SSH for as long
as it syncs; civex there serves the usual sync API on a socket only your account can
open, and SSH carries it. Signing in, files and everything the authority decides are
the same as over HTTPS.

**On the machine you SSH into** (once)

```bash
uv tool install civex                  # civex must be on PATH or in ~/.local/bin
cd ~/projects/birds && civex init      # or an existing project
civex sync authority enable
civex sync device invite laptop        # prints the laptop's invite: copy it now
```

**On each device**

```bash
civex clone ssh://you@lab-machine/~/projects/birds --invite <invite>
```

or Settings → **Sync** with that address. The address is
`ssh://[user@]host[:port]/path`: `/~/` starts in your home folder, and
`?civex=/path/to/civex` says where civex is if it is somewhere else. Hosts and
options in your `~/.ssh/config` apply (`ssh://lab/~/birds` with a `Host lab` entry).

**Good to know**

- **SSH must sign in without asking.** Syncing runs in the background, where nobody
  can type a password, so use an SSH key (an agent is fine). Where the machine needs
  a password or a code every time, open one connection that others share
  (`ControlMaster auto`, `ControlPersist 8h` in `~/.ssh/config`) and sign in to it
  once with `ssh lab`.
- **Accept the machine's host key first:** `ssh lab` once in a terminal.
- **One machine at a time.** Lab machines usually share one home folder. While a
  machine serves the project, it says so in `_civex/open-on-host.json`, and another
  machine refuses until two minutes after the last sync, because two machines writing
  one database over a network drive can damage it. Use one machine's name in the
  address.
- **The machine needs SSH forwarding** (on by default). Where an administrator has
  turned it off (`DisableForwarding`), use [Tailscale](#syncing-with-tailscale)
  instead.
- civex there stops by itself five minutes after the last request; the next sync
  starts it again (about a second). `CIVEX_SSH_COMMAND` replaces `ssh`, as
  `GIT_SSH_COMMAND` does for git.

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
device, says so and waits for you. Disconnecting leaves the data where it is.

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

## Sharing workflows and plugins

Workflows and plugins don't sync as you edit them. A plugin is code, and running
it means trusting whoever wrote it. So you share them on purpose instead, through
the authority's **library**: one person publishes, and a person on another
computer installs.

- **Nothing arrives by itself.** What you publish is kept as text in the
  authority's database. It is never written into a project's `_civex/workflows`
  or `_civex/plugins`, so nothing anyone sent can run until someone on that
  computer chooses to install it. That includes the authority itself: civex runs
  a plugin just to find out what it does, so even that waits for an install.
- **A workflow goes with its plugins.** Publishing a workflow also sends the
  plugins its steps use (not the built-in ones). Installing it installs them too.
  A workflow whose plugins are nowhere can't be published or installed.
- **Installing shows what it writes first:** every file, whether it is new, an
  update or replaces yours, who published it, its version and hash, and what
  starts the workflow by itself. A plugin's code can be read before it is
  installed, and the app asks you to confirm you trust it.
- **The authority checks what it is sent without running it.** It checks the
  names (so no file can land outside its folder) and the size (256 KB at most).
  A workflow must parse, and YAML aliases are refused, because a few lines of them
  can expand into gigabytes. A plugin must be valid Python that defines `Plugin`,
  and can't take a built-in plugin's id. What arrives is checked against its hash,
  on the authority and again when it is installed.

### Versions

Every time you publish something that has changed, it becomes the next version
(v1, v2, v3…), and every version is kept. Publishing the same text again changes
nothing.

- **A workflow remembers its plugins' versions.** It is published together with
  the plugins it uses, and remembers which version of each that was. Installing it
  installs those versions, not the newest. Publishing a new version of a plugin
  therefore changes nothing for anyone until they choose to update.
- **An update is checked before it goes in.** Each plugin version carries what it
  takes and gives (its inputs, outputs and settings). Before installing, civex
  checks every workflow on your computer that uses the plugin against the new
  version. If any would break, it names them and installs nothing unless you
  choose **Install anyway**. It checks again against the new code itself before
  writing anything.
- **Breaking changes are better as a new plugin.** A plugin keeps its id in every
  version. A change that breaks the workflows using it is better published as a
  new plugin, with a new id and name, which can be installed beside the old one.
  When you publish a version that would break a shared workflow, you are told so.
  That workflow stays on the version it was published with.
- **Rolling back** is installing an earlier version.
- **A file you changed is never overwritten** unless you say so. Updating from one
  library version to another needs no confirmation.

### Who may publish

The authority's admin decides who may publish and what:

```bash
civex sync authority library workflows   # off | workflows (the default) | all
civex sync device allow-publish laptop   # deny-publish takes it back
```

`workflows` takes workflow files only, which can use only built-in plugins and
plugins already in the library. `all` also takes plugins. No device may publish
until it is allowed, and every device may read the library. The authority's own
computer may always publish. Settings → Sync has the same controls.

### In the app and the terminal

The **Workflows** page lists your workflows and, while the project shares with a
server, the ones in the library. A **Sharing** column says how each stands:
*Not shared*, *Shared · v3*, *v2 here · v3 available*, *Changed here*, or
*In the library* (not installed). Search and the **Show…** filter work on all of
them, and each row's menu publishes, updates or installs.

Each workflow has its own page. **Overview** says what it does. **Sharing** lists
every version in the library, with the plugin versions each uses and which one
you have. From there you install, update, roll back, publish changes or remove a
version.

```bash
civex sync library list                          # what is shared, and where each stands here
civex sync library publish workflow tidy         # with the plugins it uses
civex sync library show plugin my_step -v 2      # read a version first
civex sync library install workflow tidy         # the newest; asks before writing anything
civex sync library install plugin my_step -v 1   # roll back
civex sync library install plugin my_step --force  # even though it breaks a workflow here
civex sync library remove workflow tidy -v 1     # one version; copies already installed stay
```

The authority installs from its library just as a device does. A workflow it
installs runs there like on any other computer: when someone edits a record on
the authority, or runs the workflow by hand. Changes that arrive by sync never
start a workflow, on the authority or on a device.

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

## Versions

Each civex speaks a range of sync protocol versions, and a device and the authority
use the newest both speak. Most releases don't change the protocol. When one does:

- **Update the authority first**, then the devices.
- A device that can't sync says which side to update, and waits until it is.
- The changelog gives each release's range ("sync protocol 2").

## Moving to another server

Run `civex sync connect <new address> --invite <invite>` on each device, with an
invite from the new server.

- If the new authority is empty, the first device to connect fills it.
- The rest then follow it. Any item waiting for review against the old server is
  closed, since it was about that server.

## Moving a device

The device's id and key live in `~/.civex/sync.toml`, not in the project folder.
Copying a project folder doesn't copy its identity: the copy has to be connected
with an invite of its own.

## What doesn't sync

Schemas, fields, collections, saved views, records and their files sync. These
don't, and stay on each computer:

- Saved exports (export definitions). Workflows and plugins are shared on purpose
  instead (see [Sharing workflows and plugins](#sharing-workflows-and-plugins)).
- Settings in `config.toml`: storage volumes, retention, the map, automation.
- Workflow runs and their logs.
- Pins and recent items, which are kept by each browser.
