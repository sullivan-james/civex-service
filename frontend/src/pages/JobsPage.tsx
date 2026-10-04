import { useActiveJobCount, useDrainJobs } from '../hooks/useWorkflows'
import { Page, Button } from '../components/ui'
import { RefreshCw } from '../components/ui/icons'
import JobsTable from '../components/jobs/JobsTable'

export default function JobsPage() {
  const { data: activeJobs } = useActiveJobCount()
  const drain = useDrainJobs()

  const hasActive = (activeJobs?.running ?? 0) + (activeJobs?.pending ?? 0) > 0
  const hasPending = (activeJobs?.pending ?? 0) > 0

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
        <Button
          size="sm"
          variant={hasPending ? 'primary' : 'default'}
          onClick={() => drain.mutate()}
          disabled={drain.isPending}
        >
          {drain.isPending && <RefreshCw size={12} className="animate-spin" />}
          {drain.isPending ? 'Running…' : 'Run automation'}
        </Button>
      }
    >
      {/* `?status=failed` from a dashboard link is just the status dropdown. */}
      <JobsTable />
    </Page>
  )
}
