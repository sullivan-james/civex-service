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

For a hub that owns all settings, leave out of `features`:

| Feature | What goes |
|---|---|
| `settings` | The whole Settings area and its navigation item. |
| `settings_appearance` | Appearance (`/settings/ui`). |
| `settings_retention` | Retention and its clean-ups (`/settings/retention`, `/retention/*`). |
| `settings_map` | Map tiles (`/settings/map`). |
| `settings_advanced` | Advanced (`/settings/command-line`). |
| `settings_devices` | Devices: invites, login approvals, revoke, publish (`/remote/authority*`). |
| `settings_members` | Members & access, which the host manages on its own pages. App only: there is no route behind it. |

Also leave out the features that need a machine: `volumes`, `store_admin`,
`db_admin`, `local_workflows`, `plugin_editor`, `terminal`, `updates`, `logs`,
`ai`, `open_folder`, `desktop`, `server_path_export`, `plugin_install` and
`remote_dial`. `settings` off hides the area in the app only; to refuse the
routes, leave out the section features as well.

The top-bar sync button and `/sync/review` need no feature: they appear only
for a project that follows a remote, never for a hosted authority.
