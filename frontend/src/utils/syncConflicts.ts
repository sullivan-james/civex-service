import type { ConflictTake } from '../api/remote'

/** What each button says. Which ones a row has is the server's word
 * (`conflict.takes`); this is only wording. */
const LABELS: Record<string, Partial<Record<ConflictTake, string>>> = {
  conflict: { theirs: 'Keep theirs', mine: 'Use mine', value: 'Edit…' },
  edit_vs_delete: { theirs: 'Keep it', delete: 'Delete it' },
  rejected: { theirs: 'Let it go', retry: 'Send again' },
}

export function takeLabel(kind: string, take: ConflictTake): string {
  return LABELS[kind]?.[take] ?? (take === 'theirs' ? 'Dismiss' : take)
}
