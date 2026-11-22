import { problemFrom } from '../../api/fileAccess'
import { releasesApi, type ReleaseVerify } from '../../api/releases'
import {
  job,
  refreshPlaces,
  saveBlob,
  tracked,
  waitForMove,
  type FlowContext,
} from '../files/fileFlows'
import { reportExport } from '../files/reportExport'
import { exportFolder, folderMode } from '../../utils/exportFolder'

/** Getting a release's files out, as the file flows get any selection's: a
 * job in the status bar with the server's progress, the same report of what
 * was made, and the same way of going on with what can be reached when some
 * files can't be. Only the requests differ (the release's own endpoints, which
 * lay its files out from its frozen records). */

const plural = (n: number, word: string) =>
  `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`

/** When files are out of reach, say so and offer to go on without them. */
function offerPartial(
  ctx: FlowContext,
  err: unknown,
  again: () => void,
): boolean {
  const problem = problemFrom(err)
  if (!problem) return false
  ctx.toast.error(problem.plan?.summary || problem.message, {
    duration: 15000,
    action:
      problem.code === 'files_unavailable'
        ? { label: 'Go on with what is there', onClick: again }
        : undefined,
  })
  return true
}

/** A folder of the release's files to open, on the drive holding most of them
 * (`link`), or copies on a chosen drive (`copy`), with its manifest and
 * citation beside them. */
export function exportRelease(
  ctx: FlowContext,
  name: string,
  allowPartial = false,
) {
  const mode = folderMode()
  return job(ctx, 'Finding files…', async (j) => {
    try {
      reportExport(
        ctx.toast,
        await tracked(ctx, j, (progressId) =>
          releasesApi.exportFiles(
            name,
            {
              mode,
              folder: exportFolder() ?? undefined,
              allow_partial: allowPartial,
              open: true,
            },
            progressId,
          ),
        ),
      )
    } catch (err) {
      if (!offerPartial(ctx, err, () => void exportRelease(ctx, name, true)))
        throw err
    }
  })
}

/** The release's files as one zip (only offered while it is small enough). */
export function zipRelease(
  ctx: FlowContext,
  name: string,
  allowPartial = false,
) {
  return job(ctx, 'Preparing zip…', async (j) => {
    try {
      const got = await tracked(ctx, j, (progressId) =>
        releasesApi.zipFiles(name, allowPartial, progressId),
      )
      saveBlob(got.blob, got.filename ?? `release-${name}.zip`)
    } catch (err) {
      if (!offerPartial(ctx, err, () => void zipRelease(ctx, name, true)))
        throw err
    }
  })
}

/** Put the release's files on one drive, as any move does. */
export function gatherRelease(ctx: FlowContext, name: string, volume: string) {
  return job(ctx, 'Preparing the move…', async (j) => {
    const started = await releasesApi.gatherFiles(name, volume)
    if (started.transfer_id) {
      const title = `Moving ${plural(started.files, 'file')} to ${volume}…`
      j.update({ title })
      await waitForMove(ctx, j, started.transfer_id, title)
      refreshPlaces(ctx)
    }
    ctx.toast.success(
      started.files
        ? `Moved ${plural(started.files, 'file')} of ${name} onto ${volume}.`
        : `Every file of ${name} is already on ${volume}.`,
    )
  })
}

/** Read every file of the release back against its hash: long for a large
 * release, so it runs as a job with the server's progress. */
export function deepVerify(
  ctx: FlowContext,
  name: string,
  done: (r: ReleaseVerify) => void,
) {
  return job(ctx, `Checking every file of ${name}…`, async (j) => {
    const result = await tracked(ctx, j, (progressId) =>
      releasesApi.verify(name, true, progressId),
    )
    done(result)
    if (result.matches)
      ctx.toast.success(
        `${name} is intact: ${plural(result.files_read, 'file')} read back.`,
      )
    else ctx.toast.error(`${name} does not match: ${result.problems[0] ?? ''}`)
  })
}

/** Compare a large release with the data now as a job in the status bar,
 * with the server's progress; the answer goes where the inline comparison
 * keeps it (`useReleaseComparison`). */
export function compareRelease(ctx: FlowContext, name: string) {
  return job(ctx, `Comparing ${name} with the data now…`, async (j) => {
    const result = await tracked(ctx, j, (progressId) =>
      releasesApi.compare(name, progressId),
    )
    ctx.qc.setQueryData(['records', 'release-compare', name], result)
  })
}
