import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { mount, type Unmount } from './embed'
import { Menu } from './components/ui/Menu'
import { isMounted, portalRoot } from './utils/host'
import { localFeatures } from './utils/features'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    headers: { 'content-type': 'application/json' },
  })

/** The host's own `fetch`: records what the app asked, answers like a civex. */
function hostFetch() {
  const calls: { url: string; auth: string | null }[] = []
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push({
      url,
      auth: new Headers(init?.headers).get('authorization'),
    })
    const path = new URL(url, 'http://x').pathname.replace('/jamie/q3/data', '')
    if (path === '/api/status/features')
      return json({ features: [...localFeatures], all: {} })
    if (path === '/api/me')
      return json({
        account: { name: 'you', kind: 'local', manage_url: null },
        permissions: { actions: [], all: {} },
      })
    if (path === '/api/collections' || path === '/api/store/transfers')
      return json([])
    if (path.includes('/jobs')) return json([])
    return json({})
  })
  return { fn: fn as unknown as typeof fetch, calls }
}

let unmount: Unmount | null = null
let el: HTMLElement

function start(
  options: Partial<Parameters<typeof mount>[1]> = {},
  at = '/jamie/q3/data/',
) {
  window.history.pushState({}, '', at)
  el = document.createElement('div')
  document.body.append(el)
  const host = hostFetch()
  unmount = mount(el, {
    base: '/jamie/q3/data',
    fetch: host.fn,
    ...options,
  })
  return host
}

beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia
})

afterEach(() => {
  unmount?.()
  unmount = null
  el?.remove()
  document.head.querySelectorAll('style').forEach((s) => s.remove())
  window.history.pushState({}, '', '/')
  vi.unstubAllGlobals()
})

describe('mount', () => {
  it('draws into a shadow root and every request goes through the host fetch', async () => {
    const globalFetch = vi.fn()
    vi.stubGlobal('fetch', globalFetch)
    const signedIn = hostFetch()
    const wrapped = ((i: RequestInfo | URL, init?: RequestInit) =>
      signedIn.fn(i, {
        ...init,
        headers: { ...(init?.headers as object), Authorization: 'Bearer t' },
      })) as typeof fetch
    start({ fetch: wrapped })
    const host = el.querySelector<HTMLElement>('[data-civex-embed]')!
    const root = host.shadowRoot!.querySelector('.civex-embed-root')!
    await waitFor(() => expect(root.textContent).toContain('Get started'))
    expect(isMounted()).toBe(true)
    expect(signedIn.calls.length).toBeGreaterThan(0)
    for (const call of signedIn.calls) {
      expect(call.url).toMatch(/^\/jamie\/q3\/data\/api\//)
      expect(call.auth).toBe('Bearer t')
    }
    expect(globalFetch).not.toHaveBeenCalled()
    // Nothing of the app is in the host page itself.
    expect(el.textContent).toBe('')
  })

  it('draws no chrome of its own and sets the host theme on its own element', async () => {
    start({
      boot: { theme: { '--color-accent': '#2dd4bf' }, scheme: 'dark' },
    })
    const host = el.querySelector<HTMLElement>('[data-civex-embed]')!
    expect(host.style.getPropertyValue('--color-accent')).toBe('#2dd4bf')
    expect(host.dataset.theme).toBe('dark')
    await waitFor(() =>
      expect(host.shadowRoot!.querySelector('main')).not.toBeNull(),
    )
    expect(host.shadowRoot!.querySelector('header')).toBeNull()
    expect(host.shadowRoot!.querySelector('footer')).toBeNull()
  })

  it('unmounts cleanly', async () => {
    start()
    await waitFor(() => expect(isMounted()).toBe(true))
    act(() => unmount!())
    unmount = null
    expect(el.querySelector('[data-civex-embed]')).toBeNull()
    expect(isMounted()).toBe(false)
  })
})

describe('routing', () => {
  it('opens the page at the address, within the base, and follows the history', async () => {
    const seen: string[] = []
    start({ onNavigate: (p) => seen.push(p) }, '/jamie/q3/data/collections')
    await waitFor(() => expect(seen).toContain('/collections'))

    act(() => unmount!.navigate('/schemas'))
    await waitFor(() => expect(seen[seen.length - 1]).toBe('/schemas'))
    expect(window.location.pathname).toBe('/jamie/q3/data/schemas')

    act(() => window.history.back())
    await waitFor(() => expect(seen[seen.length - 1]).toBe('/collections'))
    expect(window.location.pathname).toBe('/jamie/q3/data/collections')
  })
})

describe('portals', () => {
  it('draws menus inside the mounted tree, not in the page body', async () => {
    start()
    await waitFor(() => expect(isMounted()).toBe(true))
    const portal = portalRoot()
    expect(portal.getRootNode()).toBeInstanceOf(ShadowRoot)

    render(
      <Menu
        trigger={({ toggle }) => <button onClick={toggle}>more</button>}
        items={[{ label: 'Archive', onClick: () => {} }]}
      />,
    )
    await userEvent.click(screen.getByText('more'))
    expect(portal.textContent).toContain('Archive')
    expect(document.body.textContent).not.toContain('Archive')
  })
})

describe('style isolation', () => {
  it('keeps the stylesheet in the shadow root and out of the page', async () => {
    const before = {
      theme: document.documentElement.getAttribute('data-theme'),
      fontSize: document.documentElement.style.fontSize,
    }
    start({ boot: { scheme: 'dark' } })
    await waitFor(() => expect(isMounted()).toBe(true))
    const host = el.querySelector<HTMLElement>('[data-civex-embed]')!
    const sheet = host.shadowRoot!.querySelector('style')!.textContent!
    expect(sheet.length).toBeGreaterThan(1000)
    expect(sheet).not.toContain(':root')
    expect(sheet).not.toContain('@property')

    // The page gets only the `--tw-*` registrations: no rules for elements.
    const pageCss = [...document.head.querySelectorAll('style')]
      .map((s) => s.textContent)
      .join('')
    expect(pageCss).toContain('@property --tw-')
    expect(pageCss.replace(/@property[^{]*\{[^}]*\}/g, '').trim()).toBe('')

    expect(document.documentElement.getAttribute('data-theme')).toBe(
      before.theme,
    )
    expect(document.documentElement.style.fontSize).toBe(before.fontSize)
    expect(document.body.style.overflow).toBe('')
    expect(window.__CIVEX__).toBeUndefined()
  })
})
