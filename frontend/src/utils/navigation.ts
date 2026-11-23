/** Route changes, told to a host: each one is a `civex:navigate` CustomEvent
 * on `window` whose `detail` is `{ path }` (the path and query within the app,
 * without the base path), so a host's header can follow where the person is. */

import { isMounted } from './host'

export const NAVIGATE_EVENT = 'civex:navigate'

export interface NavigateDetail {
  path: string
}

let current = '/'

/** Where the app is now, within its base path. */
export function currentPath(): string {
  return current
}

/** Records `path` as where the app is and tells `window`. */
export function announceNavigation(path: string): void {
  current = path
  // Always reachable by a host's script, whenever it loads: it can read where
  // the app is now instead of waiting for the next route change.
  // A mounted app (`embed.tsx`) leaves the page's globals alone: its host
  // passes `onNavigate` instead.
  if (!isMounted())
    window.__CIVEX__ = {
      ...(window.__CIVEX__ ?? {}),
      navigate: { event: NAVIGATE_EVENT, current: currentPath, on: onNavigate },
    }
  window.dispatchEvent(
    new CustomEvent<NavigateDetail>(NAVIGATE_EVENT, { detail: { path } }),
  )
}

/** Calls `listener` with the current path now, and with each new one. Returns
 * a function that stops it. */
export function onNavigate(listener: (path: string) => void): () => void {
  const handler = (event: Event) =>
    listener((event as CustomEvent<NavigateDetail>).detail.path)
  window.addEventListener(NAVIGATE_EVENT, handler)
  listener(current)
  return () => window.removeEventListener(NAVIGATE_EVENT, handler)
}
