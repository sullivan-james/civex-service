import type { SyncProgress } from '../api/remote'
import { describeAmounts } from './amounts'

const PHASES: Record<string, string> = {
  copying: 'Copying the project from the server',
  filling: 'Sending this project to the server',
  files: 'Downloading files from the server',
  sending: 'Sending files to the server',
  pulling: 'Getting changes from the server',
  preparing: 'Preparing changes to send',
  pushing: 'Sending changes to the server',
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
    p.phase === 'files' || p.phase === 'sending'
      ? 'files'
      : p.phase === 'pulling' || p.phase === 'pushing'
        ? 'changes'
        : (KINDS[p.kind ?? ''] ?? '')
  // With the size known, the bar and the time left go by bytes: one big file
  // among small ones is most of the wait.
  const bytesTotal = p.bytes_total ?? 0
  const bytesDone = p.bytes_done ?? 0
  const byBytes = bytesTotal > 0
  const eta =
    byBytes && p.rate && p.rate > 0
      ? Math.max(0, bytesTotal - bytesDone) / p.rate
      : null
  const amounts = describeAmounts({
    done: p.done,
    total: p.total,
    unit: what || undefined,
    bytesDone,
    bytesTotal: byBytes ? bytesTotal : undefined,
    rate: p.rate,
    eta,
  })
  if (p.phase === 'preparing') {
    // Nothing to count yet: how many are coming is the news.
    const n = p.total != null ? `${p.total.toLocaleString()} ` : ''
    return {
      title: `Preparing ${n}changes to send`,
      detail: '',
      count: '',
      fraction: null,
    }
  }
  return {
    title: PHASES[p.phase] ?? 'Syncing',
    detail: what ? `${what} · ${count}` : count,
    count: p.owed
      ? `${amounts} · ${p.owed.toLocaleString()} not readable here`
      : amounts,
    fraction: byBytes
      ? Math.min(1, bytesDone / bytesTotal)
      : p.total != null && p.total > 0
        ? Math.min(1, p.done / p.total)
        : null,
  }
}
