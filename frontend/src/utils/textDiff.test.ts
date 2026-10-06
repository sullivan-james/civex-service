import { describe, expect, it } from 'vitest'
import { diffItems, diffText } from './textDiff'

const changed = (segs: { text: string; changed: boolean }[]) =>
  segs.filter((s) => s.changed).map((s) => s.text)

describe('diffText', () => {
  it('marks only the words each side has and the other lacks', () => {
    const d = diffText('the quick brown fox', 'the slow brown fox')!
    expect(changed(d.left)).toEqual(['quick'])
    expect(changed(d.right)).toEqual(['slow'])
    expect(d.left.map((s) => s.text).join('')).toBe('the quick brown fox')
    expect(d.right.map((s) => s.text).join('')).toBe('the slow brown fox')
  })

  it('marks an addition on one side only', () => {
    const d = diffText('site A', 'site A north')!
    expect(changed(d.left)).toEqual([])
    expect(changed(d.right).join('').trim()).toBe('north')
  })

  it('marks everything when nothing is shared, and nothing when it is the same', () => {
    expect(changed(diffText('abc', 'xyz')!.left)).toEqual(['abc'])
    expect(changed(diffText('same text', 'same text')!.left)).toEqual([])
  })

  it('gives up on texts too big to compare rather than hang', () => {
    const big = Array.from({ length: 3000 }, (_, i) => `w${i}`).join(' ')
    expect(diffText(big, big + ' x')).toBeNull()
  })
})

describe('diffItems', () => {
  it('marks the items the other list lacks', () => {
    const d = diffItems(['a', 'b'], ['b', 'c'])
    expect(d.left.filter((x) => x.changed).map((x) => x.item)).toEqual(['a'])
    expect(d.right.filter((x) => x.changed).map((x) => x.item)).toEqual(['c'])
  })
})
