/**
 * Which collections get opened most, kept in this browser (civex has no user
 * accounts to attach it to): a visit count and last-visit time per
 * collection name. The nav shows the top few, so the collections someone
 * actually works in are one click away.
 */

export const VISITS_KEY = 'civex.collectionVisits'

export interface CollectionVisit {
  count: number
  /** ms since epoch. */
  last: number
}

export type CollectionVisits = Record<string, CollectionVisit>

type ReadableStorage = Pick<Storage, 'getItem' | 'setItem'>

export function readVisits(storage: ReadableStorage): CollectionVisits {
  try {
    const parsed = JSON.parse(storage.getItem(VISITS_KEY) ?? '{}')
    if (!parsed || typeof parsed !== 'object') return {}
    const visits: CollectionVisits = {}
    for (const [name, v] of Object.entries(parsed)) {
      const { count, last } = (v ?? {}) as Partial<CollectionVisit>
      if (Number.isFinite(count) && Number.isFinite(last))
        visits[name] = { count: count as number, last: last as number }
    }
    return visits
  } catch {
    return {}
  }
}

/** Counts one more visit to `name`; storage being unavailable (private
 * mode, quota) just means nothing is remembered. */
export function recordVisit(
  storage: ReadableStorage,
  name: string,
  now: number = Date.now(),
): CollectionVisits {
  const visits = readVisits(storage)
  visits[name] = { count: (visits[name]?.count ?? 0) + 1, last: now }
  try {
    storage.setItem(VISITS_KEY, JSON.stringify(visits))
  } catch {
    /* not remembering is fine */
  }
  return visits
}

/** Up to `limit` of `names`, most-visited first (ties: most recent first).
 * Collections never visited fill any remaining places in their given order,
 * so a fresh install still shows something. */
export function topCollections(
  visits: CollectionVisits,
  names: string[],
  limit: number,
): string[] {
  const visited = names
    .filter((n) => visits[n])
    .sort(
      (a, b) =>
        visits[b].count - visits[a].count || visits[b].last - visits[a].last,
    )
  const unvisited = names.filter((n) => !visits[n])
  return [...visited, ...unvisited].slice(0, limit)
}
