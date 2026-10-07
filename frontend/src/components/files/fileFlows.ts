import type { QueryClient } from '@tanstack/react-query'
import {
  fileAccessApi,
  problemFrom,
  type ExportProblem,
  type DownloadResult,
  type FilePick,
  type FilePlanSummary,
  type FileSelection,
} from '../../api/fileAccess'
import { transfersApi } from '../../api/transfers'
import { runFileJob, type JobHandle } from '../../hooks/fileJobs'
import { errorMessage } from '../../lib/errors'
import { describeAmounts } from '../../utils/amounts'
import { percentDone } from '../../utils/transfers'
import { reportExport } from './reportExport'

export type Kind = 'open' | 'copy' | 'zip'

/** What went wrong that a person has to choose how to resolve: shown in the one
 * dialog, with the plan it was based on. */
export interface Problem {
  kind: Kind
  plan: FilePlanSummary
  /** The server's own words for it, when it has some (a drive that can't link). */
  message?: string
  /** What was being exported, and what it is called, so that going on from the
   * dialog does the same export. */
  selection?: FileSelection
  name?: string
}

interface Toasts {
  success: (m: string, o?: { duration?: number; action?: Action }) => void
  error: (m: string, o?: { duration?: number; action?: Action }) => void
  info: (m: string) => void
}
type Action = { label: string; onClick: () => void }

/** What every flow needs from the screen it was started on. They run as file
 * jobs, outside any component, so they carry on if the person navigates away. */
export interface FlowContext {
  toast: Toasts
  qc: QueryClient
  /** Show the one dialog, for something that needs a decision. */
  problem: (p: Problem) => void
  /** How often a move is checked on; tests make it instant. */
  pollMs?: number
  /** How often the server is asked how far a request has got. */
  progressMs?: number
}

const plural = (n: number, word: string) =>
  `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`

/** Run `work` as a job, and say plainly if it fails. */
async function job(
  ctx: FlowContext,
  title: string,
  work: (j: JobHandle) => Promise<void>,
): Promise<void> {
  try {
    await runFileJob({ title }, work)
  } catch (err) {
    ctx.toast.error(errorMessage(err))
  }
}

/** A plain id to tag a request with, so the server can say how far it has got. */
const newProgressId = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `p${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`

/** Ask the server, every so often, how far a tagged request has got, and show it
 * on the job: the stage in words, and a bar once it knows how many steps there
 * are. Returns how to stop. The request may not have begun yet, or be forgotten,
 * so a failed ask is just ignored. */
function watchProgress(j: JobHandle, id: string, every: number): () => void {
  let stopped = false
  const ask = async () => {
    try {
      const p = await fileAccessApi.progress(id)
      if (stopped) return
      j.update({
        detail: p.phase || undefined,
        progress:
          p.total > 0
            ? {
                fraction: Math.min(1, p.done / p.total),
                label: p.phase || 'Progress',
                count: describeAmounts({
                  done: p.done,
                  total: p.total,
                  unit: p.bytes_total ? 'files' : undefined,
                  bytesDone: p.bytes_done,
                  bytesTotal: p.bytes_total,
                  rate: p.rate,
                  eta: p.eta,
                }),
              }
            : undefined,
      })
    } catch {
      /* not begun yet, or already forgotten */
    }
  }
  const timer = setInterval(() => void ask(), every)
  return () => {
    stopped = true
    clearInterval(timer)
  }
}

/** Run one request with its progress shown on the job while it works. */
async function tracked<T>(
  ctx: FlowContext,
  j: JobHandle,
  run: (progressId: string) => Promise<T>,
): Promise<T> {
  const id = newProgressId()
  const stop = watchProgress(j, id, ctx.progressMs ?? 500)
  try {
    return await run(id)
  } finally {
    stop()
  }
}

/** The plan, when the server refused without sending one. */
async function planFor(
  selection: FileSelection,
  given?: FilePlanSummary,
): Promise<FilePlanSummary> {
  return given ?? (await fileAccessApi.plan(selection))
}

/** Open the selection as a folder of links. One request: when it can't just be
 * done, the answer says what is in the way and the dialog opens; nothing was
 * built. */
export function openAsFolder(
  ctx: FlowContext,
  selection: FileSelection,
  name: string,
) {
  return job(ctx, 'Preparing files…', async (j) => {
    const out = await tracked(ctx, j, (progressId) =>
      fileAccessApi.tryExport(selection, {
        name,
        mode: 'link',
        allowPartial: false,
        open: true,
        progressId,
      }),
    )
    if (out.kind === 'done') return reportExport(ctx.toast, out.result)
    ctx.problem({
      kind: 'open',
      selection,
      name,
      plan: await planFor(selection, out.plan),
      message: out.plan ? undefined : out.message,
    })
  })
}

/** Look at what a selection holds, then show the dialog (for "copy to a drive",
 * which always needs a choice of drive). */
export function chooseCopy(ctx: FlowContext, selection: FileSelection) {
  return job(ctx, 'Preparing files…', async (j) => {
    const plan = await tracked(ctx, j, (progressId) =>
      fileAccessApi.plan(selection, progressId),
    )
    ctx.problem({ kind: 'copy', plan, selection })
  })
}

/** Download the selection as a zip (or, for a table alone, the table); if some files can't be reached, the dialog
 * says which before anything is downloaded. */
export function downloadZip(
  ctx: FlowContext,
  selection: FileSelection,
  name: string,
  allowPartial = false,
) {
  return job(ctx, 'Preparing zip…', async (j) => {
    let got: { blob: Blob; filename: string | null }
    try {
      got = await tracked(ctx, j, (progressId) =>
        fileAccessApi.zip(selection, allowPartial, progressId, name),
      )
    } catch (err) {
      const problem = problemFrom(err)
      if (!problem) throw err
      return ctx.problem({
        kind: 'zip',
        plan: await planFor(selection, problem.plan),
        selection,
        name,
      })
    }
    const url = URL.createObjectURL(got.blob)
    const link = document.createElement('a')
    link.href = url
    link.download = got.filename ?? `${name}.zip`
    link.click()
    URL.revokeObjectURL(url)
  })
}

/** Link what can be reached (the person has seen what can't). */
export function openAvailable(
  ctx: FlowContext,
  selection: FileSelection,
  name: string,
) {
  return job(ctx, 'Opening folder…', async (j) => {
    const out = await tracked(ctx, j, (progressId) =>
      fileAccessApi.tryExport(selection, {
        name,
        mode: 'link',
        allowPartial: true,
        open: true,
        progressId,
      }),
    )
    if (out.kind === 'done') return reportExport(ctx.toast, out.result)
    // Something changed since they looked (a drive went, files moved drives).
    ctx.problem({
      kind: 'open',
      selection,
      name,
      plan: await planFor(selection, out.plan),
      message: out.plan ? undefined : out.message,
    })
  })
}

/** Copy everything that can be reached onto one drive, and open it. */
export function copyToDrive(
  ctx: FlowContext,
  selection: FileSelection,
  name: string,
  volume: string | undefined,
  /** How many files, when known (the dialog that asks which drive knows; the
   * export dialog doesn't until it has looked). */
  count?: number,
) {
  const title =
    count === undefined ? 'Copying files…' : `Copying ${plural(count, 'file')}…`
  return job(ctx, title, async (j) => {
    reportExport(
      ctx.toast,
      await tracked(ctx, j, (progressId) =>
        fileAccessApi.export(selection, {
          name,
          mode: 'copy',
          volume,
          allowPartial: true,
          open: true,
          progressId,
        }),
      ),
    )
  })
}

/** Move just the selection's files onto one drive (the ordinary move, shown in
 * the status bar), then link them as a folder and open it: one action for the
 * person, however long the move takes. */
export function moveThenOpen(
  ctx: FlowContext,
  selection: FileSelection,
  name: string,
  volume: string,
) {
  return job(ctx, 'Preparing the move…', async (j) => {
    const started = await tracked(ctx, j, (progressId) =>
      fileAccessApi.gather(selection, volume, progressId),
    )
    void ctx.qc.invalidateQueries({ queryKey: ['store'] })
    if (started.transfer_id) {
      const title = `Moving ${plural(started.files, 'file')} to ${volume}…`
      j.update({ title })
      await waitForMove(ctx, j, started.transfer_id, title)
    }

    j.update({
      title: 'Opening folder…',
      detail: undefined,
      progress: undefined,
    })
    const out = await tracked(ctx, j, (progressId) =>
      fileAccessApi.tryExport(selection, {
        name,
        mode: 'link',
        allowPartial: true,
        open: true,
        progressId,
      }),
    )
    if (out.kind === 'done') return reportExport(ctx.toast, out.result)
    ctx.problem({
      kind: 'open',
      selection,
      name,
      plan: await planFor(selection, out.plan),
      message: out.plan ? undefined : out.message,
    })
  })
}

/** Move picked files (the Files tab: a selection narrowed by place, name or
 * ticks) onto one drive, as one job: downloading any that are only on the
 * server, then the move itself, each with its progress in the status bar. */
export function moveFiles(
  ctx: FlowContext,
  pick: FilePick,
  volume: string,
  includeShared = false,
) {
  return job(ctx, 'Preparing the move…', async (j) => {
    const started = await tracked(ctx, j, (progressId) =>
      fileAccessApi.gather(
        { ...pick, include_shared: includeShared },
        volume,
        progressId,
      ),
    )
    refreshPlaces(ctx)
    const fetched = started.downloaded ?? 0
    if (started.transfer_id) {
      const title = `Moving ${plural(started.files, 'file')} to ${volume}…`
      j.update({ title, detail: undefined, progress: undefined })
      await waitForMove(ctx, j, started.transfer_id, title)
      refreshPlaces(ctx)
    }
    ctx.toast.success(
      [
        started.files ? `Moved ${plural(started.files, 'file')}` : null,
        fetched
          ? `${started.files ? 'downloaded' : 'Downloaded'} ${plural(fetched, 'file')} from the server`
          : null,
      ]
        .filter(Boolean)
        .join(' and ') + ` onto ${volume}.`,
    )
  })
}

/** Download picked files that are only on the server, as one job with its
 * progress in the status bar. */
export function downloadFiles(ctx: FlowContext, pick: FilePick) {
  return job(ctx, 'Downloading from the server…', async (j) => {
    const got = await tracked(ctx, j, (progressId) =>
      fileAccessApi.download({ ...pick, place: 'server' }, progressId),
    )
    refreshPlaces(ctx)
    ctx.toast.success(downloadReport(got))
  })
}

/** What a download did, in a person's terms: how many files came, the listed
 * rows that covers when records share files, and where any still are. */
export function downloadReport(got: DownloadResult): string {
  const parts = [`Downloaded ${plural(got.fetched, 'file')}.`]
  if (got.listed > got.fetched)
    parts.push(
      `Some records share a file, so ${got.listed.toLocaleString()} listed files are on this computer now.`,
    )
  for (const g of got.absent_where ?? [])
    parts.push(
      `${plural(g.files, 'file')} not downloaded: ${g.reason} ${g.fix}`,
    )
  return parts.join(' ')
}

/** Everything that says where files are, asked again after they moved. */
function refreshPlaces(ctx: FlowContext) {
  for (const key of ['file-listing', 'store', 'records', 'record', 'remote'])
    void ctx.qc.invalidateQueries({ queryKey: [key] })
}

/** Follow a move until it finishes, showing how far it is. A move that stops
 * for a reason a person has to deal with ends the job with that reason. */
async function waitForMove(
  ctx: FlowContext,
  j: JobHandle,
  id: string,
  title: string,
): Promise<void> {
  const wait = ctx.pollMs ?? 1000
  // The move shows itself in the status bar (with pause, speed and time left):
  // this job keeps out of sight while it waits, and is back after.
  j.update({ waiting: true })
  try {
    return await followMove(ctx, j, id, title, wait)
  } finally {
    j.update({ waiting: false })
  }
}

async function followMove(
  ctx: FlowContext,
  j: JobHandle,
  id: string,
  title: string,
  wait: number,
): Promise<void> {
  for (;;) {
    const t = await transfersApi.get(id)
    const pct = percentDone(t.progress)
    j.update({
      title,
      detail: t.status === 'queued' ? 'Waiting its turn' : t.progress.message,
      progress: { fraction: pct / 100, label: `${pct}%` },
    })
    if (t.status === 'completed') {
      void ctx.qc.invalidateQueries({ queryKey: ['store'] })
      return
    }
    if (
      (t.status === 'paused' && !t.auto_resume) ||
      t.status === 'failed' ||
      t.status === 'cancelled' ||
      t.status === 'interrupted'
    )
      throw new Error(
        `The move ${t.status === 'paused' ? 'was paused' : `ended (${t.status})`}, so the folder wasn't opened. ` +
          'Resume it in Settings → Storage → Tasks, then open the folder again.',
      )
    await new Promise((r) => setTimeout(r, wait))
  }
}

export type { ExportProblem }
