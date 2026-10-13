import {
  Link,
  NavLink,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { boot } from './host'
import { register, SLOTS } from './slots'

/** What an extension is handed instead of bundling its own: one React (two
 * copies of React in a page break hooks), the router and query client the app
 * uses, civex's own controls so an extension looks like the app, and the API
 * client (under the project's path, with the session handled). An extension is
 * built with these as externals (`window.__CIVEX__.shared.react`, ...). The
 * modules are fetched only when a page has extensions, so a local civex
 * doesn't load them all up front. */
async function sharedModules() {
  const [react, reactDom, jsxRuntime, ui, client] = await Promise.all([
    import('react'),
    import('react-dom'),
    import('react/jsx-runtime'),
    import('../components/ui'),
    import('../api/client'),
  ])
  return {
    react,
    'react-dom': reactDom,
    'react/jsx-runtime': jsxRuntime,
    // The parts of the router and the query client an extension draws with,
    // not the whole libraries (which would then all be in the app's bundle).
    'react-router': {
      Link,
      NavLink,
      useLocation,
      useNavigate,
      useParams,
      useSearchParams,
    },
    '@tanstack/react-query': { useMutation, useQuery, useQueryClient },
    '@civex/ui': ui,
    api: client.api,
  }
}

/** Puts `register`, the slot names and `shared` on `window.__CIVEX__`, then
 * imports each extension the page named. One that fails to load is reported
 * and skipped; the app starts either way, so a host's broken extension costs
 * that extension, never the project. */
export async function loadExtensions(
  urls: readonly string[] = boot().extensions ?? [],
  load: (url: string) => Promise<unknown> = (url) =>
    import(/* @vite-ignore */ url),
): Promise<void> {
  if (urls.length === 0) return
  window.__CIVEX__ = {
    ...(window.__CIVEX__ ?? {}),
    register,
    slots: Object.keys(SLOTS),
    shared: await sharedModules(),
  }
  await Promise.all(
    urls.map((url) =>
      load(url).catch((error: unknown) =>
        console.error(`civex extension ${url} failed to load`, error),
      ),
    ),
  )
}
