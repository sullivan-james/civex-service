import { afterEach, describe, expect, it } from 'vitest'
import {
  apiUrl,
  applyBootTheme,
  basePath,
  boot,
  brand,
  isEmbedded,
  loginRedirect,
  projectKey,
} from './host'

function setBase(href: string | null) {
  document.querySelector('base')?.remove()
  if (href === null) return
  const base = document.createElement('base')
  base.setAttribute('href', href)
  document.head.appendChild(base)
}

afterEach(() => {
  setBase(null)
  delete window.__CIVEX__
})

describe('where the app is served', () => {
  it('is the root, as civex serves it, when the page names no base', () => {
    expect(basePath()).toBe('')
    expect(apiUrl('/records/1')).toBe('/api/records/1')
    expect(projectKey('civex.pins')).toBe('civex.pins')
  })

  it('is the root when the base is /', () => {
    setBase('/')
    expect(basePath()).toBe('')
    expect(apiUrl('/me')).toBe('/api/me')
  })

  it('follows a host’s base path, for requests and what the browser keeps', () => {
    setBase('/p/acme/survey/')
    expect(basePath()).toBe('/p/acme/survey')
    expect(apiUrl('/records/1')).toBe('/p/acme/survey/api/records/1')
    expect(projectKey('civex.pins')).toBe('civex.pins@/p/acme/survey')
  })
})

describe('what the host said', () => {
  it('is nothing at all on a local civex', () => {
    expect(boot()).toEqual({})
    expect(loginRedirect('http://localhost:8000/records/1')).toBeNull()
  })

  it('sends a person whose session ended to sign in, and back again', () => {
    window.__CIVEX__ = { login_url: '/login' }
    const to = new URL(
      loginRedirect('https://hub.example/p/acme/survey/records/1')!,
    )
    expect(to.pathname).toBe('/login')
    expect(to.searchParams.get('next')).toBe(
      'https://hub.example/p/acme/survey/records/1',
    )
  })
})

describe('what a host may change of the look', () => {
  it('is embedded only when the boot says so', () => {
    expect(isEmbedded()).toBe(false)
    window.__CIVEX__ = { chrome: 'full' }
    expect(isEmbedded()).toBe(false)
    window.__CIVEX__ = { chrome: 'embedded' }
    expect(isEmbedded()).toBe(true)
  })

  it('is civex’s own name unless the host gave one', () => {
    expect(brand()).toEqual({ name: 'civex', logo_url: null })
    window.__CIVEX__ = { brand: { name: ' ' } }
    expect(brand().name).toBe('civex')
    window.__CIVEX__ = { brand: { name: 'Acme', logo_url: '/a.svg' } }
    expect(brand()).toEqual({ name: 'Acme', logo_url: '/a.svg' })
  })

  it('sets theme tokens on the root, and only custom properties', () => {
    const root = document.createElement('div')
    const set = applyBootTheme(root, {
      '--color-accent': '#123456',
      color: 'red',
      '--n': 3,
    })
    expect(set).toEqual(['--color-accent'])
    expect(root.style.getPropertyValue('--color-accent')).toBe('#123456')
    expect(root.style.color).toBe('')
  })

  it('applies the boot theme to the page by default', () => {
    window.__CIVEX__ = { theme: { '--color-accent': '#abcdef' } }
    applyBootTheme()
    expect(
      document.documentElement.style.getPropertyValue('--color-accent'),
    ).toBe('#abcdef')
    document.documentElement.style.removeProperty('--color-accent')
  })
})
