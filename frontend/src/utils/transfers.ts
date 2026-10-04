import type {
  Transfer,
  TransferProgress,
  TransferStatus,
} from '../api/transfers'

export const STATUS_LABEL: Record<TransferStatus, string> = {
  queued: 'Waiting',
  running: 'Running',
  paused: 'Paused',
  completed: 'Finished',
  failed: 'Stopped by an error',
  cancelled: 'Cancelled',
  interrupted: 'Interrupted',
}

/** How a status is drawn as a badge (`Badge`'s variants). */
export const STATUS_VARIANT: Record<
  TransferStatus,
  'default' | 'accent' | 'success' | 'danger'
> = {
  queued: 'default',
  running: 'accent',
  paused: 'default',
  completed: 'success',
  failed: 'danger',
  cancelled: 'default',
  interrupted: 'danger',
}

export const RESUMABLE: TransferStatus[] = ['paused', 'failed', 'interrupted']

/** Share done, 0–100; the file being copied counts, so the bar moves smoothly. */
export function percentDone(p: TransferProgress): number {
  if (p.bytes_total <= 0)
    return p.files_total > 0 && p.files_done >= p.files_total ? 100 : 0
  return Math.min(
    100,
    Math.round(((p.bytes_done + p.current_bytes) / p.bytes_total) * 100),
  )
}

/** Whether a transfer is doing something or about to: running, waiting its
 * turn, or paused only until a drive comes back. These are the ones worth
 * polling quickly and showing wherever the person is. */
export const isBusy = (t: Transfer) =>
  t.status === 'running' || t.status === 'queued' || t.auto_resume

/** How many moves are ahead of each waiting one: the running one, plus those
 * that have been waiting longer. Keyed by transfer id; only queued ones appear. */
export function queueAhead(transfers: Transfer[]): Map<string, number> {
  const running = transfers.filter((t) => t.status === 'running').length
  const waiting = transfers
    .filter((t) => t.status === 'queued')
    .sort((a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? ''))
  return new Map(waiting.map((t, i) => [t.id, running + i]))
}
