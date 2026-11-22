# Hosting civex

A host that serves many projects (civex-hub) serves the same built frontend at
a path of its own and hands it a boot object. `render_app_page(dist, base=...,
boot=...)` (`civex.server.app_page`) writes the base path into `<base href>`
and the boot object into `window.__CIVEX__`, before the app starts.

## The boot object

| Field | Meaning |
|---|---|
| `login_url` | Where to send a person whose session ended (a 401); `?next=` carries where to return. |
| `extensions` | ES modules to load. Each registers components into named slots. |
| `chrome` | `"embedded"`: the host draws the chrome. civex hides its top bar, footer, left navigation rail and the Settings item, and draws only the page. Anything else is civex's own chrome. |
| `theme` | A map of CSS custom properties set on `:root` before the first paint, for example `{"--color-accent": "#0a5"}`. Only names starting `--` with string values apply. They are inline styles, so they hold in light and dark mode alike: pick tokens that work in both. |
| `brand` | `{name, logo_url}`: shown in civex's own top bar in place of "civex". Not shown when `chrome` is `"embedded"`. |

With `chrome: "embedded"` the top bar's controls (Jump to, sync, Ask AI) go with it; Ctrl+K still opens the palette, and the host provides the rest.

Without `chrome`, `theme` and `brand` the app looks as it does on a desktop.

## A host header: the `app.header` slot

An extension registers a component in `app.header` and it is drawn at the top
of every page, above civex's own top bar (or alone, when embedded). It is given
`{ path }`, the app's current path and query, without the base path.

```js
const { register, shared } = window.__CIVEX__
const { createElement: h } = shared.react
register('app.header', ({ path }) => h('nav', null, `Project tabs at ${path}`), {
  id: 'hub-header',
})
```

Extensions use the app's React and router through `window.__CIVEX__.shared`.

## Following navigation

On every route change (and once at start) the app dispatches a
`civex:navigate` CustomEvent on `window`, whose `detail.path` is the path and
query within the app. A host page script listens for the event directly, or, if it loads later,
reads `window.__CIVEX__.navigate.current()` first.
Extensions can use `window.__CIVEX__.navigate.on(fn)`, which calls `fn(path)`
now and on each change, and returns a function that stops listening;
`navigate.current()` returns the path.

## Features a host should switch off

A host owns identity, access, settings and where data lives, so it narrows
`project.features` (`civex.domain.features`) and the app hides, and the server
refuses, what it turned off. `GET /api/status/features` returns what is on and
every feature that exists, so a host sees the whole list. A route of a feature
that is off answers 501; the app shows "Not available here" at its address as
well as hiding its navigation item.

**The rule for `settings_*` features.** A settings feature hides that section of
civex's app and refuses only the routes that *edit that section's stored
settings*. It never refuses an operational route a host's own UI drives (the
device invites, approvals and revokes under `/remote/authority*`, the retention
clean-up under `/retention/*`): those stay governed by the host's own gate and
by permissions. Reading a setting is never refused either: the app reads
some of them everywhere. `/settings/shortcut` stays under `desktop`. `settings` is the umbrella: with it off, every `settings_*`
section counts as off, in the server and the app (`features.enabled`), and
`PATCH /settings/identity` is refused too.

For a hub that owns all settings, leave out of `features`:

| Feature | What goes |
|---|---|
| `settings` | The whole Settings area and its navigation item, and every section below. Also refuses editing `/settings/identity`. |
| `settings_appearance` | Appearance; refuses edits to `/settings/ui`. |
| `settings_retention` | Retention; refuses editing `/settings/retention` (the clean-up routes stay). |
| `settings_map` | Map tiles; refuses editing `/settings/map`. |
| `settings_advanced` | Advanced; refuses changing `/settings/command-line`. |
| `settings_devices` | The Devices section of the app (what a hosted project shows in place of Sync); no route is refused. |
| `settings_members` | Members & access, which the host manages on its own pages. App only. |

Also leave out the features that need a machine: `volumes`, `store_admin`,
`db_admin`, `local_workflows`, `plugin_editor`, `terminal`, `updates`, `logs`,
`ai`, `open_folder`, `desktop`, `server_path_export`, `plugin_install` and
`remote_dial`.

The top-bar sync button and `/sync/review` need no feature: they appear only
for a project that follows a remote, never for a hosted authority.

## Permissions: the host decides, civex enforces

civex keeps no roles, members or grants. The host works out what each request's
caller may do and hands civex a `Permissions` in `Project.permissions` (from your
`project_resolver`); civex enforces exactly that, in the services (so the HTTP API
and the CLI agree) and in the sync authority (so a device is held to what its
person is). A project in a folder on a machine has `Permissions.everything()` and
is held to nothing.

### The actions

| Action | What it lets the caller do |
|---|---|
| `read` | see the project's records, history and files |
| `write_records` | add, change and restore records |
| `change_structure` | change kinds of record, fields and collections |
| `add_files` | cite or upload a file a record did not hold |
| `delete_files` | let go of a file a record held |
| `delete` | delete records, collections and kinds of record |
| `notes` | write, change and delete notes on records |
| `views` | save and change filters, exports and the Analytics page |
| `manage_members` | the host's own; civex has no member endpoints to guard |
| `manage_devices` | every `/remote/authority*` route: invite, approve, revoke devices |

`manage_files` still works as a name for `add_files` plus `delete_files`: grant it,
deny it or ask it, and it means both. It is never reported on its own.

Every action can be limited to collections, `read` included:

```python
Permissions.of("read", "write_records", "notes",
               collections=[a, b],          # the actions, only in a and b
               read_collections=[a, b, c])  # may see a, b and c; others do not exist
Permissions.of("read", "write_records").without(["write_records"], [x])  # all but x
```

`read` stays project-wide unless you pass `read_collections` (or put a `read`
scope or denial in `Permissions` yourself). A collection created later is seen
exactly when the rule says: always under "all but these", never under a list.

**Notes and views used to be part of writing records.** A host that says nothing
about `notes` or `views` (neither grants nor denies them) keeps that: they go where
`write_records` goes, denials included. Say anything about one, or call
`.lacking("notes", "views")`, and it is yours to decide.

### A collection without `read` is not there

For a caller who cannot read a collection, civex behaves as if it did not exist:

- it is absent from lists, counts, search, summaries, charts, dashboards, saved
  views, exports and downloads, history and audit (a record's entries too), notes,
  referrers and file lists;
- asking for it, or for anything in it, directly is a **404**, never a 403, so its
  existence is not given away;
- writes that would touch it (creating a record in it, moving a record into it,
  referencing a record of it) are refused the same way, and a record's file
  downloaded by hash is a 404 unless a record the caller can read holds it too;
- a dashboard card over it stays in the layout and says "not available to you".

This is one rule at the one layer every query goes through (`civex.db.read_scope`),
not a check each route remembers. What it does *not* hide, by design:

- **Kinds of record and their fields are project-wide.** civex has no per-schema
  scope: a collection holds records of every kind. A hidden collection's records
  are hidden; the names of kinds and fields remain visible to everyone who can read
  anything, so do not put secrets in kind or field names.
- **A reference** from a record the caller can read to a record in a hidden *global*
  collection shows the raw id, with no label, and cannot be followed (404).
- Routers about the project as a whole (storage, transfers, buckets, retention,
  releases) answer 403 to a caller who cannot read every collection.
- A record moved out of a hidden collection carries its earlier history with it.
- Deleting a record that records in a hidden collection still refer to is refused
  ("referenced by records you cannot see"), forced or not, so nothing is left
  dangling and nothing hidden is touched.
- Content with no use by any record (just uploaded, or left behind until clean-up)
  is not tied to a collection, so anyone who knows its hash can fetch it.

### Devices and pushes

`Project.permissions` is used for a device's sync requests too: your resolver sees
the device's request and should return the permissions of the person the device
belongs to. A push is judged with the same object: a change in a collection the
device may not read or write, a file it may not add or let go of, or a record
that is held here in such a collection (whatever the push says) is refused through the
ordinary rejected-change path with `code: "permission"`.

`Project.push_accepted` is called once after a push has been committed and took at
least one change, with a `civex.domain.sync.PushAccepted` (device, actor, the
ids of the changes taken, counts by status and by kind, and their feed numbers).
It replaces reading push responses in middleware; an exception in it is logged and
never fails the push.
