/** The records a person is reviewing, in order, kept for the browser tab so the
 * record pages can show where they are in it (the stepper) and settled ones stay
 * on the list after they have nothing left to settle. */

const KEY = 'civex.syncReview'

export interface ReviewStep {
  id: string
  name: string
}

export function readReview(): ReviewStep[] | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : null
    return Array.isArray(parsed) &&
      parsed.every((s) => s && typeof s.id === 'string')
      ? (parsed as ReviewStep[])
      : null
  } catch {
    return null
  }
}

export function saveReview(steps: ReviewStep[]): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(steps))
  } catch {
    // Without storage the stepper starts afresh on each page; nothing is lost.
  }
}

export function endReview(): void {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    // Nothing kept, nothing to clear.
  }
}

/** The records that have something to settle, once each, in review order. */
export function stepsFrom(
  conflicts: {
    entity_id: string
    entity_type: string
    record_name: string | null
  }[],
): ReviewStep[] {
  const seen = new Map<string, ReviewStep>()
  for (const c of conflicts)
    if (c.entity_type === 'record' && !seen.has(c.entity_id))
      seen.set(c.entity_id, {
        id: c.entity_id,
        name: c.record_name ?? c.entity_id.slice(0, 8),
      })
  return [...seen.values()]
}
