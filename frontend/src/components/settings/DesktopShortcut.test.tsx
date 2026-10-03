import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { DesktopShortcut } from './DesktopShortcut'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

function stub(initial: { exists: boolean; path: string | null }) {
  let state = initial
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname === '/api/settings/shortcut') {
        calls.push(init?.method ?? 'GET')
        if (init?.method === 'POST') state = { exists: true, path: state.path }
        return json(state)
      }
      return json({})
    }),
  )
  return calls
}
const renderIt = (prompt = false) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <DesktopShortcut prompt={prompt} />
    </QueryClientProvider>,
  )
afterEach(() => vi.unstubAllGlobals())

describe('DesktopShortcut', () => {
  it('adds the shortcut and then says so', async () => {
    const calls = stub({
      exists: false,
      path: '/home/u/Desktop/Civex - p.desktop',
    })
    renderIt()
    await userEvent.click(
      await screen.findByRole('button', { name: /Add desktop shortcut/ }),
    )
    expect(
      await screen.findByText('Desktop shortcut added'),
    ).toBeInTheDocument()
    expect(calls).toContain('POST')
  })

  it('on the first-run page, goes away once there is one or there is no Desktop', async () => {
    stub({ exists: true, path: '/d/x' })
    const { container } = renderIt(true)
    await waitFor(() => expect(container).toBeEmptyDOMElement())
    vi.unstubAllGlobals()
    stub({ exists: false, path: null })
    const second = renderIt(true)
    await new Promise((r) => setTimeout(r, 50))
    expect(second.container.querySelector('button')).toBeNull()
  })
})
