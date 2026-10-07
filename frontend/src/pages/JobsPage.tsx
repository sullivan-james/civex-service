import { useState } from 'react'
import {
  useActiveJobCount,
  useAutomation,
  useDrainJobs,
  useResumeAutomation,
} from '../hooks/useWorkflows'
import { Page, Button } from '../components/ui'
import { RefreshCw } from '../components/ui/icons'
import JobsTable from '../components/jobs/JobsTable'
import { StopAutomationDialog } from '../components/workflows/StopAutomationDialog'

export default function JobsPage() {
  const { data: activeJobs } = useActiveJobCount()
  const { data: automation } = useAutomation()
  const drain = useDrainJobs()
  const resume = useResumeAutomation()
  const [stopping, setStopping] = useState(false)

  const hasActive = (activeJobs?.running ?? 0) + (activeJobs?.pending ?? 0) > 0
  const hasPending = (activeJobs?.pending ?? 0) > 0
  const paused = automation?.paused ?? false

  return (
    <Page
      title="Runs"
      meta={
        hasActive ? (
          <span className="flex items-center gap-1 text-accent">
            <RefreshCw size={12} className="animate-spin" /> live
          </span>
        ) : undefined
      }
      action={
        paused ? (
          <Button
            size="sm"
            variant="primary"
            onClick={() => resume.mutate()}
            disabled={resume.isPending}
          >
            {resume.isPending ? 'Resuming…' : 'Resume automation'}
          </Button>
        ) : (
          <>
            <Button
              size="sm"
              variant={hasActive ? 'danger' : 'default'}
              onClick={() => setStopping(true)}
            >
              Stop automation…
            </Button>
            <Button
              size="sm"
              variant={hasPending ? 'primary' : 'default'}
              onClick={() => drain.mutate()}
              disabled={drain.isPending}
            >
              {drain.isPending && (
                <RefreshCw size={12} className="animate-spin" />
              )}
              {drain.isPending ? 'Running…' : 'Run automation'}
            </Button>
          </>
        )
      }
    >
      {paused && (
        <p
          role="status"
          className="rounded-md border border-attention-muted bg-attention-subtle px-4 py-3 text-sm text-attention"
        >
          Automation is paused: nothing new will run until you resume.
        </p>
      )}
      {/* `?status=failed` from a dashboard link is just the status dropdown. */}
      <JobsTable />
      {stopping && <StopAutomationDialog onClose={() => setStopping(false)} />}
    </Page>
  )
}
