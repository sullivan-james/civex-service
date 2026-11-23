import type { RecordSync } from '../api/records'
import { ago } from './syncState'

/** What to say about a record's standing with its authority, or null when
 * there is nothing to say (no authority here, or this project is one). */
export function recordSyncText(s: RecordSync, now = Date.now()): string | null {
  if (s.state === 'not_connected' || s.state === 'held_here') return null
  const server = s.remote ? s.remote.replace(/^https?:\/\//, '') : 'the server'
  const files =
    s.files_waiting > 0
      ? ` · ${s.files_waiting} of ${s.files} files not sent`
      : ''
  switch (s.state) {
    case 'pending':
      return `Waiting to send (${s.pending} ${s.pending === 1 ? 'change' : 'changes'})${files}`
    case 'first_upload':
      return `First upload to ${server} not finished${files}`
    case 'refused':
      return `Refused: ${s.message ?? 'the server would not take it'}${files}`
    case 'conflict':
      return `Conflict with ${server}${files}`
    default:
      return `Synced with ${server}${s.synced_at ? ` · ${ago(s.synced_at, now)}` : ''}${files}`
  }
}
