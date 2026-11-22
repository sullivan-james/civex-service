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
| `theme` | A map of CSS custom properties set on `:root` before the first paint, for example `{"--color-accent": "#0a5"}`. Only names starting `--` with string values apply. |
| `brand` | `{name, logo_url}`: shown in civex's own top bar in place of "civex". Not shown when `chrome` is `"embedded"`. |

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
query within the app. A host page script listens for the event directly.
Extensions can use `window.__CIVEX__.navigate.on(fn)`, which calls `fn(path)`
now and on each change, and returns a function that stops listening;
`navigate.current()` returns the path.
