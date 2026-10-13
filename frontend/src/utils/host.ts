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
