import type { TransferProgress, TransferStatus } from '../api/transfers'

export const STATUS_LABEL: Record<TransferStatus, string> = {
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
