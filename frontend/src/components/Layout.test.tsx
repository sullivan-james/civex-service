import { afterEach, describe, expect, it } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useNavigate } from 'react-router'
import { fakeServer } from './files/testSupport'
import { ToastProvider } from './ui/ToastProvider'
import { clearSlots, register } from '../utils/slots'
import { onNavigate } from '../utils/navigation'
import Layout from './Layout'

afterEach(() => {
  clearSlots()
  delete window.__CIVEX__
})

function Go() {
  const navigate = useNavigate()
  return (
    <button onClick={() => navigate('/collections?x=1')}>
      go to collections
    </button>
  )
}

function renderLayout(path = '/collections') {
  fakeServer({})
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <Go />
          <Layout>
            <p>the page</p>
          </Layout>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('the app’s chrome', () => {
  it('is civex’s own by default: top bar, navigation, Settings and footer', () => {
    renderLayout()
    expect(screen.getByText('civex')).toBeInTheDocument()
    expect(
      screen.getByRole('navigation', { name: 'Primary' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Settings' })).toBeInTheDocument()
    expect(screen.getByText('Licenses & policies')).toBeInTheDocument()
    expect(screen.getByText('the page')).toBeInTheDocument()
  })

  it('is left to the host when the boot says embedded: only the page remains', () => {
    window.__CIVEX__ = { chrome: 'embedded' }
    renderLayout()
    expect(screen.getByText('the page')).toBeInTheDocument()
    expect(screen.queryByRole('banner')).toBeNull()
    expect(screen.queryByRole('navigation', { name: 'Primary' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Settings' })).toBeNull()
    expect(screen.queryByText('Licenses & policies')).toBeNull()
  })

  it('names the app as the host does, with its logo', () => {
    window.__CIVEX__ = { brand: { name: 'Acme Hub', logo_url: '/logo.svg' } }
    renderLayout()
    expect(screen.getByText('Acme Hub')).toBeInTheDocument()
    expect(screen.queryByText('civex')).toBeNull()
    expect(document.querySelector('img[src="/logo.svg"]')).not.toBeNull()
  })
})

describe('the app.header slot', () => {
  it.each(['full', 'embedded'] as const)(
    'draws the host’s header, told the path, above the page (%s)',
    (chrome) => {
      window.__CIVEX__ = { chrome }
      register('app.header', ({ path }: { path: string }) => (
        <div data-testid="host-header">tabs at {path}</div>
      ))
      renderLayout('/schemas')
      expect(screen.getByTestId('host-header')).toHaveTextContent(
        'tabs at /schemas',
      )
    },
  )
})

describe('route changes', () => {
  it('are told to the host as civex:navigate events, and to extensions', () => {
    renderLayout('/schemas')
    const heard: string[] = []
    const seen: string[] = []
    const off = onNavigate((p) => seen.push(p))
    const listener = (e: Event) =>
      heard.push((e as CustomEvent<{ path: string }>).detail.path)
    window.addEventListener('civex:navigate', listener)
    act(() => screen.getByText('go to collections').click())
    window.removeEventListener('civex:navigate', listener)
    off()
    expect(heard).toEqual(['/collections?x=1'])
    expect(seen).toEqual(['/schemas', '/collections?x=1'])
  })
})
