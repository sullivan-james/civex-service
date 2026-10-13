import { afterEach, describe, expect, it } from 'vitest'
import { apiUrl, basePath, boot, loginRedirect, projectKey } from './host'

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
