import { describe, it, expect } from 'vitest'
import { renderHook } from '@testing-library/react'
import type { MouseEvent } from 'react'
import { useRangeSelect, withRange } from './useRangeSelect'

const IDS = ['a', 'b', 'c', 'd', 'e']
const click = (shiftKey: boolean) => ({ shiftKey }) as unknown as MouseEvent

/** One click on a box: the click event first, then the change handler. */
function press(
  r: ReturnType<typeof useRangeSelect>,
  id: string,
  shift: boolean,
) {
  r.onClick(click(shift))
  return r.rangeFor(id)
}

describe('useRangeSelect', () => {
  it('treats a plain click as just that box', () => {
    const { result } = renderHook(() => useRangeSelect(IDS))
    expect(press(result.current, 'b', false)).toBeNull()
    expect(press(result.current, 'd', false)).toBeNull()
  })

  it('takes everything between the last box clicked and a shift-clicked one', () => {
    const { result } = renderHook(() => useRangeSelect(IDS))
    press(result.current, 'b', false)

    expect(press(result.current, 'd', true)).toEqual(['b', 'c', 'd'])
  })

  it('works upwards too, in the order shown', () => {
    const { result } = renderHook(() => useRangeSelect(IDS))
    press(result.current, 'd', false)

    expect(press(result.current, 'a', true)).toEqual(['a', 'b', 'c', 'd'])
  })

  it('starts the next range from the box just shift-clicked', () => {
    const { result } = renderHook(() => useRangeSelect(IDS))
    press(result.current, 'a', false)
    press(result.current, 'c', true)

    expect(press(result.current, 'e', true)).toEqual(['c', 'd', 'e'])
  })

  it('is a plain click when there was no earlier box, or it is the same box', () => {
    const { result } = renderHook(() => useRangeSelect(IDS))
    expect(press(result.current, 'c', true)).toBeNull() // nothing clicked before
    expect(press(result.current, 'c', true)).toBeNull() // the same box again
  })

  it('does not carry shift over to the next click', () => {
    const { result } = renderHook(() => useRangeSelect(IDS))
    press(result.current, 'a', false)
    press(result.current, 'c', true)

    expect(press(result.current, 'e', false)).toBeNull()
  })

  it('does not guess when the first box is no longer in the list', () => {
    const { result, rerender } = renderHook(({ ids }) => useRangeSelect(ids), {
      initialProps: { ids: IDS },
    })
    press(result.current, 'a', false)
    rerender({ ids: ['x', 'y', 'z'] }) // another page, a new filter

    expect(press(result.current, 'z', true)).toBeNull()
  })

  it('follows the order it is given now, not the order it was first given', () => {
    const { result, rerender } = renderHook(({ ids }) => useRangeSelect(ids), {
      initialProps: { ids: IDS },
    })
    press(result.current, 'a', false)
    rerender({ ids: ['e', 'd', 'c', 'b', 'a'] }) // sorted the other way

    expect(press(result.current, 'c', true)).toEqual(['c', 'b', 'a'])
  })
})

describe('useRangeSelect with a label in the way', () => {
  it('still counts a shift-click when the box then gets a second click without shift', () => {
    const { result } = renderHook(() => useRangeSelect(IDS))
    press(result.current, 'b', false)

    // Click on the label text (shift held), then the browser's own click on the
    // box (which may not say shift), then the change.
    result.current.onClick(click(true))
    result.current.onClick(click(false))

    expect(result.current.rangeFor('d')).toEqual(['b', 'c', 'd'])
  })

  it('forgets a shift-click that was never followed by a change', async () => {
    const { result } = renderHook(() => useRangeSelect(IDS))
    press(result.current, 'b', false)
    result.current.onClick(click(true)) // e.g. a disabled box: no change comes
    await new Promise((r) => setTimeout(r, 600))

    expect(result.current.rangeFor('d')).toBeNull()
  })
})

describe('withRange', () => {
  it('adds or removes every id, leaving the rest', () => {
    const start = new Set(['a', 'z'])
    expect([...withRange(start, ['b', 'c'], true)].sort()).toEqual([
      'a',
      'b',
      'c',
      'z',
    ])
    expect([...withRange(new Set(['a', 'b', 'c']), ['b', 'c'], false)]).toEqual(
      ['a'],
    )
    expect([...start]).toEqual(['a', 'z']) // the original is untouched
  })
})
