import type { NavTarget } from './pins'

/** What the Ctrl+K palette lists: results of a typed search, or -- with
 * nothing typed -- the pins and recents, so the commonest jumps need no
 * typing at all. */

export interface PaletteGroup {
  heading: string
  items: NavTarget[]
}

export const GROUP_LIMIT = 6

/** Every space-separated word of `query` appears somewhere in `text`,
 * ignoring case. An empty query matches everything. */
export function matchesQuery(query: string, text: string): boolean {
  const haystack = text.toLowerCase()
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => haystack.includes(word))
}

function pick(query: string, items: NavTarget[]): NavTarget[] {
  return items
    .filter((t) => matchesQuery(query, `${t.label} ${t.context ?? ''}`))
    .slice(0, GROUP_LIMIT)
}

export interface PaletteSources {
  pins: NavTarget[]
  recents: NavTarget[]
  collections: NavTarget[]
  schemas: NavTarget[]
  views: NavTarget[]
  records: NavTarget[]
}

/** The groups to show for `query`, empty groups left out. Places are the
 * drilled-down spots someone pinned or opened lately -- they have no list of
 * their own to search, so those are what is matched. */
export function buildGroups(
  query: string,
  src: PaletteSources,
): PaletteGroup[] {
  const q = query.trim()
  const groups: PaletteGroup[] = q
    ? [
        { heading: 'Collections', items: pick(q, src.collections) },
        { heading: 'Schemas', items: pick(q, src.schemas) },
        { heading: 'Saved filters', items: pick(q, src.views) },
        // Records were already matched by the server.
        { heading: 'Records', items: src.records.slice(0, GROUP_LIMIT) },
        {
          heading: 'Places',
          items: pick(
            q,
            [...src.pins, ...src.recents].filter(
              (t, i, all) =>
                t.kind === 'place' &&
                all.findIndex((o) => o.key === t.key) === i,
            ),
          ),
        },
      ]
    : [
        { heading: 'Pinned', items: src.pins },
        {
          heading: 'Recent',
          items: src.recents.filter(
            (r) => !src.pins.some((p) => p.key === r.key),
          ),
        },
      ]
  return groups.filter((g) => g.items.length > 0)
}
