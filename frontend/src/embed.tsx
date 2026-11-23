/** civex's app, to put inside another page: `mount(element, options)` draws
 * its views into `element` and returns a function that takes them out again.
 *
 * This is a second entry of the frontend build (`vite.embed.config.ts`,
 * `embed.js`, with its own React): the standalone app is unchanged. The host
 * says where the app lives and how requests are signed in; everything the
 * standalone app takes from the page it is served in (`<base href>`,
 * `window.__CIVEX__`, the global `fetch`, `document.body`, `<html>`) is taken
 * from `options` instead (`utils/host`).
 *
 *  - Styles: the app draws in a shadow root, so its stylesheet (Tailwind's
 *    reset included) cannot reach the host's elements and the host's cannot
 *    reach it. The host's colours come in as CSS custom properties
 *    (`boot.theme`), which pass through a shadow boundary.
 *  - Floating UI (menus, popovers, dialogs) is drawn inside the same root.
 *  - Routing: a router with `basename` = `base` on the real browser history,
 *    so the address bar, back/forward and deep links all work in the host's
 *    page. A host that keeps its own router sees the navigations through
 *    `onNavigate`, and moves the app with `navigate`.
 *  - One app at a time per page.
 */
import { createRoot } from 'react-dom/client'
import { BrowserRouter, useLocation, useNavigate } from 'react-router'
import { useEffect, useRef } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import styles from './index.css?inline'
import App from './App'
import { ThemeProvider } from './hooks/useTheme'
import { ToastProvider } from './components/ui/ToastProvider'
import { createQueryClient } from './queryClient'
import { announceNavigation } from './utils/navigation'
import { scopeCss } from './utils/scopeCss'
import { setMountedHost, type Boot } from './utils/host'

export interface MountOptions {
  /** Where the app is: the path its pages and API live under, such as
   * `/jamie/q3/data`. */
  base: string
  /** What the host says (`utils/host` `Boot`): `theme` (CSS custom
   * properties, by name), `scheme`, `brand`, `login_url`. */
  boot?: Boot
  /** Makes every request the app makes: the host adds its sign-in here. The
   * browser's `fetch` if left out. */
  fetch?: typeof fetch
  /** Called with the app's path and query, within `base`, now and on every
   * route change. */
  onNavigate?: (path: string) => void
}

/** Takes the app out. */
export interface Unmount {
  (): void
  /** Moves the app to `path` (within `base`), as a link inside it would. */
  navigate: (path: string) => void
}

const PROPERTIES_ID = 'civex-embed-properties'

function Bridge({
  onNavigate,
  navigateRef,
}: {
  onNavigate?: (path: string) => void
  navigateRef: { current: ((path: string) => void) | null }
}) {
  const navigate = useNavigate()
  const location = useLocation()
  useEffect(() => {
    navigateRef.current = (path) => void navigate(path)
    return () => {
      navigateRef.current = null
    }
  }, [navigate, navigateRef])
  const path = location.pathname + location.search
  useEffect(() => {
    announceNavigation(path)
    onNavigate?.(path)
  }, [path, onNavigate])
  return null
}

export function mount(el: HTMLElement, options: MountOptions): Unmount {
  const boot = options.boot ?? {}
  const host = document.createElement('div')
  host.dataset.civexEmbed = ''
  host.style.display = 'block'
  if (boot.scheme) host.dataset.theme = boot.scheme
  for (const [name, value] of Object.entries(boot.theme ?? {}))
    if (name.startsWith('--') && typeof value === 'string')
      host.style.setProperty(name, value)

  const shadow = host.attachShadow({ mode: 'open' })
  const { scoped, properties } = scopeCss(styles)
  const style = document.createElement('style')
  style.textContent = scoped
  const root = document.createElement('div')
  root.className = 'civex-embed-root'
  const portal = document.createElement('div')
  portal.className = 'civex-embed-portal'
  shadow.append(style, root, portal)

  if (properties && !document.getElementById(PROPERTIES_ID)) {
    const registrations = document.createElement('style')
    registrations.id = PROPERTIES_ID
    registrations.textContent = properties
    document.head.append(registrations)
  }

  el.append(host)
  const mountedHost = {
    base: options.base,
    boot: { ...boot, chrome: 'embedded' as const },
    fetch: options.fetch,
    portal,
    root,
  }
  setMountedHost(mountedHost)

  const navigateRef = { current: null as ((path: string) => void) | null }
  const queryClient = createQueryClient()
  const reactRoot = createRoot(root)
  reactRoot.render(
    <ThemeProvider target={host} scheme={boot.scheme}>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <BrowserRouter
            basename={options.base.replace(/\/+$/, '') || undefined}
          >
            <Bridge onNavigate={options.onNavigate} navigateRef={navigateRef} />
            <App />
          </BrowserRouter>
        </ToastProvider>
      </QueryClientProvider>
    </ThemeProvider>,
  )

  const unmount = (() => {
    reactRoot.unmount()
    queryClient.clear()
    host.remove()
    setMountedHost(null)
  }) as Unmount
  unmount.navigate = (path) => navigateRef.current?.(path)
  return unmount
}
