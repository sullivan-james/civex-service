import type { TransferProgress, TransferStatus } from '../api/transfers'

export const STATUS_LABEL: Record<TransferStatus, string> = {
  running: 'Running',
  paused: 'Paused',
  completed: 'Finished',
  failed: 'Stopped by an error',
  cancelled: 'Cancelled',
  interrupted: 'Interrupted',
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

export function formatEta(seconds: number | null): string {
  if (seconds == null) return '—'
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${s % 60}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}
