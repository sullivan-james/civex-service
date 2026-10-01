/**
 * Pins and recents, kept in this browser (civex has no user accounts to
 * attach them to). A pin is a shortcut to something the researcher keeps
 * coming back to -- a saved filter, a collection, a record, or a drilled-down
 * place in the explorer. Recents are the last few things opened, so "pick up
 * where you left off" needs no bookkeeping from the user.
 */

export const PINS_KEY = 'civex.pins'
export const RECENTS_KEY = 'civex.recents'
export const MAX_RECENTS = 12

export type PinKind = 'view' | 'collection' | 'record' | 'place'

export interface NavTarget {
  /** Identity: the same thing always has the same key, so pinning twice is
   * one pin and reopening something moves it up the recents. */
  key: string
  kind: PinKind
  label: string
  /** App path (with querystring) that opens it. */
  to: string
  /** Small muted detail, e.g. a record's schema or a view's schema. */
  context?: string
  /** Saved filters only: what is needed to count the matching records. */
  schema?: string
  view?: string
}

type ReadableStorage = Pick<Storage, 'getItem' | 'setItem'>

export const targetKeys = {
  view: (schema: string, view: string) => `view:${schema}/${view}`,
  collection: (id: string) => `collection:${id}`,
  record: (id: string) => `record:${id}`,
  place: (to: string) => `place:${to}`,
}

const KINDS: PinKind[] = ['view', 'collection', 'record', 'place']

function isTarget(v: unknown): v is NavTarget {
  if (!v || typeof v !== 'object') return false
  const t = v as Partial<NavTarget>
  return (
    typeof t.key === 'string' &&
    typeof t.label === 'string' &&
    typeof t.to === 'string' &&
    KINDS.includes(t.kind as PinKind)
  )
}

/** Parses a stored list, dropping anything malformed. */
export function parseTargets(raw: string | null): NavTarget[] {
  try {
    const parsed = JSON.parse(raw ?? '[]')
    return Array.isArray(parsed) ? parsed.filter(isTarget) : []
  } catch {
    return []
  }
}

function write(storage: ReadableStorage, key: string, list: NavTarget[]) {
  try {
    storage.setItem(key, JSON.stringify(list))
  } catch {
    /* no storage: nothing is remembered */
  }
}

export function readPins(storage: ReadableStorage): NavTarget[] {
  try {
    return parseTargets(storage.getItem(PINS_KEY))
  } catch {
    return []
  }
}

/** Pins `target`, or unpins it when already pinned. New pins go last, so the
 * nav keeps the order they were added in. Returns the new list. */
export function togglePin(
  storage: ReadableStorage,
  target: NavTarget,
): NavTarget[] {
  const pins = readPins(storage)
  const next = pins.some((p) => p.key === target.key)
    ? pins.filter((p) => p.key !== target.key)
    : [...pins, target]
  write(storage, PINS_KEY, next)
  return next
}

export function readRecents(storage: ReadableStorage): NavTarget[] {
  try {
    return parseTargets(storage.getItem(RECENTS_KEY))
  } catch {
    return []
  }
}

/** Notes that `target` was just opened: it goes to the front, any earlier
 * entry for it is dropped, and the list is capped. */
export function pushRecent(
  storage: ReadableStorage,
  target: NavTarget,
): NavTarget[] {
  const next = [
    target,
    ...readRecents(storage).filter((r) => r.key !== target.key),
  ].slice(0, MAX_RECENTS)
  write(storage, RECENTS_KEY, next)
  return next
}
