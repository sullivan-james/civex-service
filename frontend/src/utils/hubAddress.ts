/** The address of a repository on a host, as someone would paste it: the
 * browser address (`https://hub.example/owner/repo`) or the sync address
 * (`.../owner/repo/data`). Both name the same place. */
export interface HubAddress {
  /** What the project connects to. */
  address: string
  /** `owner/repo` when the address names one, else the host. */
  name: string
  /** The repository's own page, for a link; null for a bare server. */
  page: string | null
  /** Where a person asks for access or approves a device (same as `page`). */
  host: string
}

export function parseHubAddress(raw: string): HubAddress | null {
  const text = raw.trim()
  if (!text) return null
  let url: URL
  try {
    url = new URL(
      /^[a-z][a-z0-9+.-]*:\/\//i.test(text) ? text : `https://${text}`,
    )
  } catch {
    return null
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') return null
  const parts = url.pathname.split('/').filter(Boolean)
  if (parts[parts.length - 1] === 'data') parts.pop()
  const origin = url.origin
  if (parts.length === 2) {
    const [owner, repo] = parts
    return {
      address: `${origin}/${owner}/${repo}/data`,
      name: `${owner}/${repo}`,
      page: `${origin}/${owner}/${repo}`,
      host: url.host,
    }
  }
  const path = parts.length ? `/${parts.join('/')}` : ''
  return {
    address: `${origin}${path}`,
    name: url.host,
    page: null,
    host: url.host,
  }
}

/** The page where a person approves the code, with the code filled in (a
 * server may have put it there already). */
export function approvalUrl(verifyUrl: string, code: string): string {
  try {
    const url = new URL(verifyUrl)
    if (!url.searchParams.has('code')) url.searchParams.set('code', code)
    return url.toString()
  } catch {
    return verifyUrl
  }
}
