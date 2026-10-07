import type { SyncProgress } from '../api/remote'
import { describeAmounts } from './amounts'

const PHASES: Record<string, string> = {
  copying: 'Copying the project from the server',
  filling: 'Sending this project to the server',
  history: 'Fetching earlier history',
  files: 'Downloading files from the server',
}

const KINDS: Record<string, string> = {
  schema: 'schemas',
  field: 'fields',
  dataset: 'collections',
  view: 'saved views',
  record: 'records',
}

export interface SyncProgressText {
  title: string
  /** "records · 12,000 of 48,000" */
  detail: string
  /** "12,000 of 48,000 records": beside a bar. */
  count: string
  /** 0 to 1, or null when how many there are isn't known. */
  fraction: number | null
}

/** How a long sync step is described, wherever it is shown (the status bar, the
 * Sync settings), so it reads the same in both. */
export function describeSyncProgress(p: SyncProgress): SyncProgressText {
  const count =
    p.total != null
      ? `${p.done.toLocaleString()} of ${p.total.toLocaleString()}`
      : p.done.toLocaleString()
  const what =
    p.phase === 'history'
      ? 'changes'
      : p.phase === 'files'
        ? 'files'
        : (KINDS[p.kind ?? ''] ?? '')
  return {
    title: PHASES[p.phase] ?? 'Syncing',
    detail: what ? `${what} · ${count}` : count,
    count: describeAmounts({
      done: p.done,
      total: p.total,
      unit: what || undefined,
      bytesDone: p.bytes_done,
      rate: p.rate,
    }),
    fraction:
      p.total != null && p.total > 0 ? Math.min(1, p.done / p.total) : null,
  }
}
