# @civex/ui

civex's controls (`Button`, `DataTable`, `Page`, `Modal`, ...) and theme, for
pages a host builds around the app, such as the hub's shell, so they look and
behave like civex.

It is not a copy and is not published: `index.ts` re-exports
`frontend/src/components/ui` and `theme.css` imports `frontend/src/index.css`,
so the app and a host change together. A host depends on this folder from a
civex checkout (a git dependency, or a Vite alias):

```ts
// vite.config.ts of the host's shell
resolve: { alias: { '@civex/ui': '<civex>/frontend/packages/ui' } }
```

```ts
import '@civex/ui/theme.css'
import { Button, Page } from '@civex/ui'
```

The controls use React Router and TanStack Query, so the host's page renders
them inside a router and a `QueryClientProvider`, as the app does.

**Extensions** (ES modules a host loads into the app's own pages, drawn into
named slots; `src/utils/slots.ts`) do not bundle this package: they read it,
React and the router from `window.__CIVEX__.shared`, so the page has one React.
