import type { RemoteStatus, SyncResult } from '../api/remote'

export interface SyncNotice {
  variant: 'success'
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

/** Whether to toast a sync that has just finished, and what to say. A toast is
 * for good news that passes: a sync they asked for is always answered, one that
 * ran by itself only when it did something, so a quiet project stays quiet.
 * Trouble is not toasted: a failed sync and values waiting to be reviewed stay
 * in the status bar (`useSyncTasks`) with their actions until dealt with, and
 * saying them twice is noise. Returns null when nothing new has happened since
 * `before`. */
export function syncNotice(
  before: Pick<RemoteStatus, 'last_synced_at'> | null,
  after: RemoteStatus,
  asked: boolean,
): SyncNotice | null {
  if (!before) return null // the first look: nothing has just finished
  if (after.last_synced_at === before.last_synced_at) return null
  const r = after.last_result
  if (!r) return asked ? { variant: 'success', message: 'Synced' } : null
  // What is left for a person (clashes, refusals) is the status bar's to say.
  const done = { ...r, conflicts: 0, rejected: 0 }
  const did = done.pulled || done.pushed || done.files_sent
  if (!did && (!asked || r.conflicts || r.rejected)) return null
  return { variant: 'success', message: describeResult(done) }
}
