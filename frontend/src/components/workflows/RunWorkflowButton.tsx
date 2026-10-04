import { useState } from 'react'
import type { Workflow } from '../../api/workflows'
import { useRunWorkflow } from '../../hooks/useWorkflows'
import { Button, Menu, useToast } from '../ui'
import { ChevronDown, Play } from '../ui/icons'
import { WorkflowRunModal } from './WorkflowRunModal'

const needsFiles = (wf: Workflow) =>
  Object.values(wf.inputs ?? {}).some((i) => i.type === 'files')

/** Run a workflow on this record, from the page itself. One workflow is one
 * button; several are one button that lists them. A workflow that needs no
 * files just starts, and says so with a way to see the run; only one that
 * wants files asks for them, in a dialog that doesn't make you look at the
 * record's ID. */
export function RunWorkflowButton({
  workflows,
  recordId,
  onStarted,
}: {
  workflows: Workflow[]
  recordId: string
  /** The person asked to see the run that was just started. */
  onStarted: () => void
}) {
  const toast = useToast()
  const run = useRunWorkflow()
  const [asking, setAsking] = useState<Workflow | null>(null)

  if (workflows.length === 0) return null

  function started(wf: Workflow) {
    toast.success(`Started ${wf.name}.`, {
      action: { label: 'View run', onClick: onStarted },
    })
  }

  function choose(wf: Workflow) {
    if (needsFiles(wf)) {
      setAsking(wf)
      return
    }
    run.mutate(
      { name: wf.name, recordId },
      {
        onSuccess: () => started(wf),
        onError: (err) =>
          toast.error(
            `Couldn't start ${wf.name}: ${err instanceof Error ? err.message : 'something went wrong'}`,
          ),
      },
    )
  }

  const busy = run.isPending
  const single = workflows.length === 1 ? workflows[0] : null

  return (
    <>
      {single ? (
        <Button disabled={busy} onClick={() => choose(single)}>
          <Play size={14} aria-hidden="true" />
          {busy ? 'Starting…' : `Run ${single.name}`}
        </Button>
      ) : (
        <Menu
          items={workflows.map((wf) => ({
            label: wf.name,
            icon: Play,
            onClick: () => choose(wf),
          }))}
          trigger={({ toggle, open }) => (
            <Button
              disabled={busy}
              aria-haspopup="menu"
              aria-expanded={open}
              onClick={toggle}
            >
              <Play size={14} aria-hidden="true" />
              {busy ? 'Starting…' : 'Run workflow'}
              <ChevronDown size={14} aria-hidden="true" />
            </Button>
          )}
        />
      )}
      {asking && (
        <WorkflowRunModal
          workflow={asking}
          recordId={recordId}
          onStarted={() => started(asking)}
          onClose={() => setAsking(null)}
        />
      )}
    </>
  )
}
