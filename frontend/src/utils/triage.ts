/**
 * Triage: working through a list of records one at a time. Starting one
 * freezes the list of record ids (in the order shown) in this tab's session
 * storage and puts a token for it in the record's URL. Frozen, because the
 * list is usually a filter like "not reviewed", and a record drops out of it
 * the moment it is marked -- a live list would shift under the researcher.
 *
 * A record opened any other way (search, a link, a new tab) carries no token,
 * so there is no list and no bar.
 */

export const TRIAGE_PARAM = 'triage'
const SESSION_PREFIX = 'civex.triage.'
const FIELD_PREFIX = 'civex.triageField.'

export interface TriageSession {
  id: string
  /** What is being worked through, e.g. a saved filter's name. */
  label: string
  ids: string[]
  /** Records marked reviewed so far, in this session. */
  reviewed: string[]
}

type ReadableStorage = Pick<Storage, 'getItem' | 'setItem'>

function newId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID().slice(0, 8)
    : Math.random().toString(36).slice(2, 10)
}

function save(storage: ReadableStorage, session: TriageSession) {
  try {
    storage.setItem(SESSION_PREFIX + session.id, JSON.stringify(session))
  } catch {
    /* no storage: the session can't outlive this page */
  }
}

export function readSession(
  storage: ReadableStorage,
  id: string | null,
): TriageSession | null {
  if (!id) return null
  try {
    const parsed = JSON.parse(storage.getItem(SESSION_PREFIX + id) ?? 'null')
    if (
      !parsed ||
      typeof parsed.label !== 'string' ||
      !Array.isArray(parsed.ids) ||
      !Array.isArray(parsed.reviewed)
    )
      return null
    return {
      id,
      label: parsed.label,
      ids: parsed.ids.filter((x: unknown) => typeof x === 'string'),
      reviewed: parsed.reviewed.filter((x: unknown) => typeof x === 'string'),
    }
  } catch {
    return null
  }
}

export function startSession(
  storage: ReadableStorage,
  label: string,
  ids: string[],
): TriageSession {
  const session = { id: newId(), label, ids, reviewed: [] }
  save(storage, session)
  return session
}

/** Notes `recordId` as reviewed (once). */
export function markReviewed(
  storage: ReadableStorage,
  session: TriageSession,
  recordId: string,
): TriageSession {
  if (session.reviewed.includes(recordId)) return session
  const next = { ...session, reviewed: [...session.reviewed, recordId] }
  save(storage, next)
  return next
}

export interface TriagePosition {
  /** 1-based. */
  index: number
  total: number
  previousId: string | null
  nextId: string | null
}

/** Where `recordId` sits in the session; null when it isn't part of it (the
 * token belongs to some other list), which hides the bar. */
export function positionOf(
  session: TriageSession,
  recordId: string,
): TriagePosition | null {
  const i = session.ids.indexOf(recordId)
  if (i === -1) return null
  return {
    index: i + 1,
    total: session.ids.length,
    previousId: session.ids[i - 1] ?? null,
    nextId: session.ids[i + 1] ?? null,
  }
}

export function triagePath(recordId: string, sessionId: string): string {
  return `/records/${recordId}?${TRIAGE_PARAM}=${encodeURIComponent(sessionId)}`
}

interface FieldLike {
  name: string
  type: string
}

/** The boolean field that means "reviewed" for a schema: the researcher's
 * remembered choice if it still exists, else one named `reviewed`, else the
 * first boolean field. Null when the schema has no boolean field at all. */
export function reviewedField(
  storage: ReadableStorage,
  schemaName: string,
  fields: FieldLike[],
): string | null {
  const booleans = fields.filter((f) => f.type === 'boolean').map((f) => f.name)
  let chosen: string | null = null
  try {
    chosen = storage.getItem(FIELD_PREFIX + schemaName)
  } catch {
    /* fall through to the default */
  }
  if (chosen && booleans.includes(chosen)) return chosen
  return booleans.includes('reviewed') ? 'reviewed' : (booleans[0] ?? null)
}

export function rememberReviewedField(
  storage: ReadableStorage,
  schemaName: string,
  field: string,
) {
  try {
    storage.setItem(FIELD_PREFIX + schemaName, field)
  } catch {
    /* the default is used next time */
  }
}
