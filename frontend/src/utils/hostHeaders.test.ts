import { afterEach, describe, expect, it, vi } from 'vitest'
import { applyHostHeaders, setMountedHost } from './host'

const xhr = () => ({ setRequestHeader: vi.fn() }) as unknown as XMLHttpRequest

afterEach(() => {
  setMountedHost(null)
  delete window.__CIVEX_HEADERS__
})

describe('host headers on XHR', () => {
  it('adds the headers an unmounted host page supplies', () => {
    window.__CIVEX_HEADERS__ = () => ({ Authorization: 'Bearer t' })
    const x = xhr()
    applyHostHeaders(x)
    expect(x.setRequestHeader).toHaveBeenCalledWith('Authorization', 'Bearer t')
  })

  it('adds the headers a mounted host supplies', () => {
    setMountedHost({
      base: '/a/b/data',
      boot: {},
      headers: () => ({ Authorization: 'Bearer m' }),
      portal: document.body,
      root: document.body,
    })
    const x = xhr()
    applyHostHeaders(x)
    expect(x.setRequestHeader).toHaveBeenCalledWith('Authorization', 'Bearer m')
  })

  it('adds nothing when the host says nothing', () => {
    const x = xhr()
    applyHostHeaders(x)
    expect(x.setRequestHeader).not.toHaveBeenCalled()
  })
})
