import type { RemoteStatus, SyncResult } from '../api/remote'

export interface SyncNotice {
  variant: 'success' | 'error'
  message: string
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`
}

/** What a finished sync was about, in a sentence. */
export function describeResult(r: SyncResult): string {
  const parts: string[] = []
  if (r.pulled) parts.push(`received ${plural(r.pulled, 'change')}`)
  if (r.pushed) parts.push(`sent ${plural(r.pushed, 'change')}`)
  if (r.files_sent) parts.push(`uploaded ${plural(r.files_sent, 'file')}`)
  let text = parts.length ? `Synced: ${parts.join(', ')}` : 'Already up to date'
  if (r.conflicts) text += `. ${plural(r.conflicts, 'value')} to review`
  if (r.rejected) text += `. ${plural(r.rejected, 'change')} refused`
  return text
}

/** Whether to tell the person about a sync that has just finished, and what to
 * say. A sync they asked for is always reported; one that ran by itself only when
 * it did something or went wrong, so a quiet project stays quiet. Returns null
 * when nothing new has happened since `before`. */
export function syncNotice(
  before: Pick<
    RemoteStatus,
    'last_synced_at' | 'last_error' | 'last_error_at'
  > | null,
  after: RemoteStatus,
  asked: boolean,
): SyncNotice | null {
  if (!before) return null // the first look: nothing has just finished
  // A failure that keeps repeating is told once (when it starts or changes),
  // not at every retry; one the person asked for is always told.
  const failed =
    !!after.last_error &&
    after.last_error_at !== before.last_error_at &&
    (asked || after.last_error !== before.last_error)
  if (failed)
    return { variant: 'error', message: `Could not sync: ${after.last_error}` }
  if (after.last_synced_at === before.last_synced_at) return null
  const r = after.last_result
  if (!r) return asked ? { variant: 'success', message: 'Synced' } : null
  const did = r.pulled || r.pushed || r.files_sent || r.conflicts || r.rejected
  if (!did && !asked) return null
  return {
    variant: r.conflicts || r.rejected ? 'error' : 'success',
    message: describeResult(r),
  }
}
