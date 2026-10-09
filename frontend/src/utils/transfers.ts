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
/** Files a move has dealt with: moved or copied, already on the target (only
 * the original had to go, or nothing at all), or failed. */
export const filesHandled = (p: TransferProgress) =>
  p.files_done + p.files_skipped + p.files_failed

/** "1,519 of 1,595 files, 76 already there": how far a move is, by file. */
export function filesLine(p: TransferProgress): string {
  const there =
    p.files_skipped > 0
      ? `, ${p.files_skipped.toLocaleString()} already there`
      : ''
  return `${filesHandled(p).toLocaleString()} of ${p.files_total.toLocaleString()} files${there}`
}

export function percentDone(p: TransferProgress): number {
  if (p.bytes_total <= 0)
    return p.files_total > 0 && filesHandled(p) >= p.files_total ? 100 : 0
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

/** What a move is, in a line: `ing` for one under way ("Moving 1,519 files to
 * vol-b"), else as asked ("Move 1,519 files onto vol-b"). A move of picked
 * files counts from its plan (the request's file list isn't sent back), and
 * says "Copy" when every file is copied rather than moved: a file whose drive
 * is the home of a collection that uses it stays there too. */
export function describeTransfer(t: Transfer, ing = false): string {
  const to = `${ing ? 'to' : 'onto'} ${t.spec.targets.join(', ')}`
  // The status bar is short: a drain or gather there says what, not where to.
  if (t.kind === 'drain')
    return ing
      ? `Emptying ${t.spec.sources.join(', ')}`
      : `Empty ${t.spec.sources.join(', ')} ${to}`
  if (t.kind === 'files') {
    const n = t.plan?.files ?? t.progress.files_total
    const copied = t.plan?.copied ?? 0
    const all = n > 0 && copied === n
    const verb = all ? (ing ? 'Copying' : 'Copy') : ing ? 'Moving' : 'Move'
    const some =
      copied > 0 && !all
        ? ` (${copied.toLocaleString()} copied, not moved)`
        : ''
    return `${verb} ${n.toLocaleString()} ${n === 1 ? 'file' : 'files'} ${to}${some}`
  }
  const c = t.spec.collection_ids.length
  const what = `${c} ${c === 1 ? 'collection' : 'collections'}`
  return ing ? `Gathering ${what}` : `Gather ${what} ${to}`
}
