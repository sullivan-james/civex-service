/** Where this app is served and what the page that served it said: the one
 * place the app learns it may not be alone at `/`.
 *
 * `civex serve` serves the app at `/` and says nothing more. A host that
 * serves many projects (the hub) serves the same build at a path of its own,
 * `/p/<owner>/<project>/`, by writing it into the page's `<base href>`, and
 * may put a boot object in `window.__CIVEX__` (`server/app_page.py` renders
 * both). Everything the app requests or links to is under that path, and
 * what it keeps in the browser is kept per project. */

/** What a host may say before the app starts. Who the person is and what they
 * may do are not here: those are `GET /me`, asked like any other data. */
export interface Boot {
  /** Where to send a person whose session has ended (a 401). */
  login_url?: string | null
  /** ES modules to load; each registers components into named slots
   * (`utils/slots.ts`). */
  extensions?: string[]
  /** `"embedded"`: the host draws the page's chrome (header, tabs, navigation)
   * and civex draws only the page: no top bar, footer, left rail or Settings
   * item. Anything else, or nothing, is civex's own chrome. */
  chrome?: 'full' | 'embedded'
  /** CSS custom properties to set on `:root`, by name (`--color-accent`):
   * the host's colours for the app (see `index.css` for the tokens). */
  theme?: Record<string, string>
  /** What to call the app and where its logo is, in place of "civex". */
  brand?: { name?: string; logo_url?: string }
}

declare global {
  interface Window {
    __CIVEX__?: Boot & Record<string, unknown>
  }
}

/** The path the app is served at, without a trailing slash: `''` at `/`,
 * `/p/acme/survey` under a host. Read from `<base href>`, which a host sets. */
export function basePath(doc: Document = document): string {
  const href = doc.querySelector('base')?.getAttribute('href')
  if (!href) return ''
  try {
    return new URL(
      href,
      doc.location?.href ?? 'http://localhost/',
    ).pathname.replace(/\/+$/, '')
  } catch {
    return ''
  }
}

/** The address of an API path (`/records/1` → `/api/records/1`, under the
 * base path). Every request the app makes is built here or in `api/client`. */
export function apiUrl(path: string): string {
  return `${basePath()}/api${path}`
}

/** The boot object the page carried, or nothing. */
export function boot(): Boot {
  const value = typeof window === 'undefined' ? undefined : window.__CIVEX__
  return value && typeof value === 'object' ? value : {}
}

/** A browser-storage key for this project: the key itself at `/`, so a
 * local civex keeps what it kept, and the key with the base path under a
 * host, so pins and recents of one project never show in another. */
export function projectKey(key: string): string {
  const base = basePath()
  return base ? `${key}@${base}` : key
}

/** Where to go once a session has ended: the host's sign-in page, told where
 * to come back to. None when the host has no such page (a local civex). */
export function loginRedirect(
  here: string = typeof window === 'undefined' ? '' : window.location.href,
): string | null {
  const login = boot().login_url
  if (!login) return null
  const url = new URL(login, here || 'http://localhost/')
  if (here) url.searchParams.set('next', here)
  return url.toString()
}

/** Whether the host draws the chrome (`boot().chrome === "embedded"`). */
export function isEmbedded(): boolean {
  return boot().chrome === 'embedded'
}

/** The name and logo the top bar shows: the host's, else civex's. */
export function brand(): { name: string; logo_url: string | null } {
  const given = boot().brand
  const name =
    typeof given?.name === 'string' && given.name.trim()
      ? given.name.trim()
      : 'civex'
  const logo =
    typeof given?.logo_url === 'string' && given.logo_url
      ? given.logo_url
      : null
  return { name, logo_url: logo }
}

/** Sets the boot `theme` tokens on `root`. Only custom properties (`--x`) with
 * string values are applied; anything else is ignored, so a theme can't set
 * arbitrary style. Returns the names it set. */
export function applyBootTheme(
  root: HTMLElement = document.documentElement,
  theme: Record<string, unknown> | undefined = boot().theme,
): string[] {
  if (!theme || typeof theme !== 'object') return []
  const set: string[] = []
  for (const [name, value] of Object.entries(theme)) {
    if (!name.startsWith('--') || typeof value !== 'string') continue
    root.style.setProperty(name, value)
    set.push(name)
  }
  return set
}
