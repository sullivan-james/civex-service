import type { QueryClient } from '@tanstack/react-query'
import { recordsApi, type BulkEditRequest } from '../../api/records'
import { invalidateRecordNames } from '../../hooks/useRecordName'
import { job, tracked, type FlowContext } from '../files/fileFlows'

const records = (n: number) =>
  `${n.toLocaleString()} record${n === 1 ? '' : 's'}`

/** Everything that may show the records an edit changed, or the runs it
 * started. */
function refresh(qc: QueryClient, runs: number) {
  qc.invalidateQueries({ queryKey: ['records'] })
  qc.invalidateQueries({ queryKey: ['record'] })
  qc.invalidateQueries({ queryKey: ['record-bulk-edit-plan'] })
  qc.invalidateQueries({ queryKey: ['audit'] })
  invalidateRecordNames(qc)
  if (runs) {
    qc.invalidateQueries({ queryKey: ['jobs'] })
    qc.invalidateQueries({ queryKey: ['automation'] })
  }
}

/** Set fields on many records, as a job: it is saved a chunk at a time on the
 * server, shows how far it has got in the status bar (and carries on there if
 * the person goes elsewhere), and can be stopped; what it changed by then
 * stays, and making the same edit again finishes it. */
export function editRecords(ctx: FlowContext, body: BulkEditRequest) {
  return job(ctx, 'Changing records…', async (j) => {
    try {
      const result = await tracked(
        ctx,
        j,
        (progressId) => recordsApi.bulkEdit(body, progressId),
        true,
      )
      const left = result.skipped
        ? `, ${result.skipped.toLocaleString()} left as ${result.skipped === 1 ? 'it was' : 'they were'}`
        : ''
      ctx.toast.success(
        result.stopped
          ? `Stopped: ${records(result.changed)} changed`
          : `${records(result.changed)} changed${left}`,
      )
      refresh(ctx.qc, result.runs)
    } catch (err) {
      // Some of it may have been saved before it failed.
      refresh(ctx.qc, 0)
      throw err
    }
  })
}
