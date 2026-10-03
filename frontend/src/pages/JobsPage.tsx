import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { useActiveJobCount, useDrainJobs } from '../hooks/useWorkflows'
import { Page, Button, Chip } from '../components/ui'
import { RefreshCw } from '../components/ui/icons'
import JobsTable from '../components/jobs/JobsTable'

const STATUS_OPTIONS = [
  '',
  'pending',
  'running',
  'completed',
  'failed',
] as const

export default function JobsPage() {
  // Seeds from `?status=` so an analytics widget's "View runs" link lands
  // pre-filtered -- read once on mount, same as any other uncontrolled
  // initial state (the buttons below are the source of truth afterwards).
  const [searchParams] = useSearchParams()
  const [statusFilter, setStatusFilter] = useState<string | undefined>(
    () => searchParams.get('status') || undefined,
  )
  const { data: activeJobs } = useActiveJobCount()
  const drain = useDrainJobs()

  const hasActive = (activeJobs?.running ?? 0) + (activeJobs?.pending ?? 0) > 0
  const hasPending = (activeJobs?.pending ?? 0) > 0

  function handleStatusFilter(s: string) {
    setStatusFilter(s || undefined)
  }

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
      <div className="flex items-center gap-2">
        {STATUS_OPTIONS.map((s) => (
          <Chip
            key={s || 'all'}
            selected={(statusFilter ?? '') === s}
            onClick={() => handleStatusFilter(s)}
          >
            {s || 'All'}
          </Chip>
        ))}
      </div>

      <JobsTable statusFilter={statusFilter} />
    </Page>
  )
}
