import { describe, it, expect, afterEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useIsDesktop } from './useIsDesktop'

afterEach(() => {
  delete (window as { pywebview?: unknown }).pywebview
})

describe('useIsDesktop', () => {
  it('is false in a browser', () => {
    expect(renderHook(() => useIsDesktop()).result.current).toBe(false)
  })

  it('turns true when pywebview arrives after the page loaded', () => {
    // The Windows app: window.pywebview appears late, then pywebviewready.
    const { result } = renderHook(() => useIsDesktop())
    expect(result.current).toBe(false)
    act(() => {
      ;(window as { pywebview?: unknown }).pywebview = { api: {} }
      window.dispatchEvent(new Event('pywebviewready'))
    })
    expect(result.current).toBe(true)
  })
})
