import { renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { useAnchoredPosition } from './useAnchoredPosition'

const realHeight = window.innerHeight
const realWidth = window.innerWidth

function el(
  rect: Partial<DOMRect>,
  size: { height?: number; width?: number } = {},
) {
  return {
    getBoundingClientRect: () => ({
      top: 0,
      bottom: 0,
      left: 0,
      right: 0,
      width: 0,
      ...rect,
    }),
    scrollHeight: size.height ?? 0,
    offsetWidth: size.width ?? 0,
  } as unknown as HTMLElement
}

function place(
  anchor: Partial<DOMRect>,
  panel: { height: number; width: number },
  window_ = 600,
) {
  window.innerHeight = window_
  window.innerWidth = 1000
  const { result } = renderHook(() =>
    useAnchoredPosition(
      { current: el(anchor) },
      { current: el({}, panel) },
      'right',
    ),
  )
  return result.current!
}

afterEach(() => {
  window.innerHeight = realHeight
  window.innerWidth = realWidth
})

describe('useAnchoredPosition', () => {
  it('opens below the trigger when it fits', () => {
    const p = place(
      { top: 100, bottom: 130, left: 800, right: 900, width: 100 },
      { height: 200, width: 300 },
    )
    expect(p.top).toBe(134)
    expect(p.left).toBe(600) // right edges lined up
  })

  it('opens above when there is more room there, never past the window', () => {
    const p = place(
      { top: 500, bottom: 530, left: 0, right: 100, width: 100 },
      { height: 200, width: 100 },
    )
    expect(p.top + Math.min(200, p.maxHeight)).toBeLessThanOrEqual(496)
    expect(p.top).toBeGreaterThanOrEqual(8)
  })

  it('caps a panel taller than the room, so it scrolls inside itself', () => {
    const p = place(
      { top: 160, bottom: 196, left: 0, right: 100, width: 100 },
      { height: 900, width: 100 },
      360,
    )
    expect(p.top).toBe(200)
    expect(p.top + p.maxHeight).toBeLessThanOrEqual(352)
  })
})
