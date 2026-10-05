import type { RemoteStatus } from '../api/remote'

export interface SyncButtonState {
  /** What the button says. */
  label: string
  /** `needed`: there is something to send or a problem; `ok`: nothing to do. */
  tone: 'ok' | 'needed' | 'busy' | 'error'
}

/** "just now", "3 min ago", "2 h ago", "5 d ago". */
export function ago(iso: string | null, now: number = Date.now()): string {
  if (!iso) return 'never'
  const seconds = Math.max(
    0,
    Math.round((now - new Date(iso).getTime()) / 1000),
  )
  if (seconds < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

/** What the top-bar sync button shows: whether a sync is needed. Only what this
 * computer knows is used (unsent changes, the last outcome); it does not ask the
 * authority, so changes made elsewhere show up once the next sync looks. */
export function syncButtonState(
  s: RemoteStatus,
  starting = false,
  now: number = Date.now(),
): SyncButtonState {
  if (s.running || starting) return { label: 'Syncing…', tone: 'busy' }
  if (s.last_error) return { label: 'Sync failed', tone: 'error' }
  if (s.pending > 0)
    return { label: `Sync · ${s.pending} to send`, tone: 'needed' }
  if (s.open_conflicts > 0)
    return { label: `Sync · ${s.open_conflicts} to review`, tone: 'needed' }
  return {
    label: s.last_synced_at ? `Synced ${ago(s.last_synced_at, now)}` : 'Sync',
    tone: 'ok',
  }
}
