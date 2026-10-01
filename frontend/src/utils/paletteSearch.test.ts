import { describe, it, expect } from 'vitest'
import { GROUP_LIMIT, buildGroups, matchesQuery } from './paletteSearch'
import type { NavTarget } from './pins'

const t = (
  kind: NavTarget['kind'],
  label: string,
  context?: string,
): NavTarget => ({
  key: `${kind}:${label}`,
  kind,
  label,
  to: `/${label}`,
  context,
})

const none = {
  pins: [],
  recents: [],
  collections: [],
  schemas: [],
  views: [],
  records: [],
}

describe('matchesQuery', () => {
  it('needs every word, in any order, ignoring case', () => {
    expect(matchesQuery('table miss', 'Missing selection_table')).toBe(true)
    expect(matchesQuery('table zzz', 'Missing selection_table')).toBe(false)
    expect(matchesQuery('', 'anything')).toBe(true)
  })
})

describe('buildGroups', () => {
  it('shows pins then recents (without repeating a pin) when nothing is typed', () => {
    const pinned = t('collection', 'Whales')
    const groups = buildGroups('  ', {
      ...none,
      pins: [pinned],
      recents: [pinned, t('record', 'rec-1')],
    })
    expect(groups.map((g) => g.heading)).toEqual(['Pinned', 'Recent'])
    expect(groups[1].items.map((i) => i.label)).toEqual(['rec-1'])
  })

  it('groups matches by type and leaves out empty groups', () => {
    const groups = buildGroups('whale', {
      ...none,
      collections: [t('collection', 'Whale song'), t('collection', 'Birds')],
      schemas: [t('place', 'Recording', 'Schema')],
      views: [t('view', 'Whale recordings', 'recording')],
    })
    expect(groups.map((g) => g.heading)).toEqual([
      'Collections',
      'Saved filters',
    ])
    expect(groups[0].items).toHaveLength(1)
  })

  it('matches places among pins and recents once each, and caps a group', () => {
    const place = t('place', 'Selections in Whale 7')
    const many = Array.from({ length: GROUP_LIMIT + 4 }, (_, i) =>
      t('collection', `Whale ${i}`),
    )
    const groups = buildGroups('whale', {
      ...none,
      pins: [place],
      recents: [place],
      collections: many,
    })
    expect(groups.find((g) => g.heading === 'Collections')!.items).toHaveLength(
      GROUP_LIMIT,
    )
    expect(groups.find((g) => g.heading === 'Places')!.items).toHaveLength(1)
  })
})
