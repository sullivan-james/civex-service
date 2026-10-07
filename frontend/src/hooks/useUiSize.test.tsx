import { describe, it, expect, afterEach, beforeEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import {
  applyUiSize,
  setUiSize,
  stepUiSize,
  useDesktopZoomKeys,
  useUiSize,
} from './useUiSize'

function press(key: string) {
  window.dispatchEvent(new KeyboardEvent('keydown', { key, metaKey: true }))
}

beforeEach(() => {
  localStorage.clear()
  applyUiSize()
})
afterEach(() => {
  delete (window as { pywebview?: unknown }).pywebview
})

describe('UI size', () => {
  it('scales the root font size and remembers it', () => {
    const { result } = renderHook(() => useUiSize())
    expect(result.current).toBe(100)
    act(() => setUiSize(90))
    expect(result.current).toBe(90)
    expect(document.documentElement.style.fontSize).toBe('90%')
    expect(localStorage.getItem('civex-ui-size')).toBe('90')
    act(() => setUiSize(100))
    expect(document.documentElement.style.fontSize).toBe('')
  })

  it('steps within its sizes and back to normal', () => {
    const { result } = renderHook(() => useUiSize())
    act(() => {
      for (let i = 0; i < 6; i++) stepUiSize(-1)
    })
    expect(result.current).toBe(80)
    act(() => stepUiSize(1))
    expect(result.current).toBe(90)
    act(() => stepUiSize(0))
    expect(result.current).toBe(100)
  })

  it('takes ⌘ + − 0 in the desktop app only', () => {
    renderHook(() => useDesktopZoomKeys())
    const { result } = renderHook(() => useUiSize())
    act(() => press('-'))
    expect(result.current).toBe(100) // a browser zooms itself
    ;(window as { pywebview?: unknown }).pywebview = { api: {} }
    act(() => press('-'))
    expect(result.current).toBe(90)
    act(() => press('='))
    act(() => press('='))
    expect(result.current).toBe(110)
    act(() => press('0'))
    expect(result.current).toBe(100)
  })
})
