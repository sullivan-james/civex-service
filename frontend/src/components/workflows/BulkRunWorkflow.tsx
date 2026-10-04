import { useNavigate } from 'react-router'
import type { Workflow } from '../../api/workflows'
import { useRunWorkflowOnMany } from '../../hooks/useWorkflows'
import { Button, Menu, useToast } from '../ui'
import { ChevronDown, Play } from '../ui/icons'

const needsFiles = (wf: Workflow) =>
  Object.values(wf.inputs ?? {}).some((i) => i.type === 'files')

/** The workflows that can be run on records of this schema without being given
 * anything per run: the ones for this schema (or for any), and not those that
 * ask for files. */
export function bulkRunnable(
  workflows: Workflow[] | undefined,
  schemaName: string,
): Workflow[] {
  return (workflows ?? []).filter(
    (wf) =>
      (!wf.record_schema || wf.record_schema === schemaName) && !needsFiles(wf),
  )
}

/** "Run workflow" for a selection of records: pick a workflow and each selected
 * record gets a run, queued in one request. Says how many started and, plainly,
 * any it could not run on and why. */
export function BulkRunWorkflow({
  workflows,
  recordIds,
  onStarted,
}: {
  workflows: Workflow[]
  recordIds: string[]
  /** Called once the runs are queued, e.g. to clear the selection. */
  onStarted?: () => void
}) {
  const toast = useToast()
  const navigate = useNavigate()
  const run = useRunWorkflowOnMany()

  if (workflows.length === 0) return null

  function choose(wf: Workflow) {
    run.mutate(
      { name: wf.name, recordIds },
      {
        onSuccess: ({ started, skipped }) => {
          if (started.length > 0)
            toast.success(
              `Started ${wf.name} on ${started.length.toLocaleString()} ${started.length === 1 ? 'record' : 'records'}.`,
              {
                action: {
                  label: 'View runs',
                  onClick: () =>
                    navigate(`/runs?workflow=${encodeURIComponent(wf.name)}`),
                },
              },
            )
          if (skipped.length > 0)
            toast.error(
              `Couldn't run ${wf.name} on ${skipped.length.toLocaleString()}: ${skipped[0].reason}${skipped.length > 1 ? ` (and ${skipped.length - 1} more)` : ''}`,
            )
          onStarted?.()
        },
        onError: (err) =>
          toast.error(
            `Couldn't start ${wf.name}: ${err instanceof Error ? err.message : 'something went wrong'}`,
          ),
      },
    )
  }

  return (
    <Menu
      items={workflows.map((wf) => ({
        label: wf.name,
        icon: Play,
        onClick: () => choose(wf),
      }))}
      trigger={({ toggle, open }) => (
        <Button
          size="sm"
          disabled={run.isPending}
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={toggle}
        >
          <Play size={14} aria-hidden="true" />
          {run.isPending
            ? 'Starting…'
            : `Run workflow on ${recordIds.length.toLocaleString()}`}
          <ChevronDown size={14} aria-hidden="true" />
        </Button>
      )}
    />
  )
}
