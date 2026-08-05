import { useState } from 'react'
import { useActiveJobCount, useDrainJobs } from '../hooks/useWorkflows'
import { PageHeader, Button } from '../components/ui'
import JobsTable from '../components/jobs/JobsTable'

const STATUS_OPTIONS = [
  '',
  'pending',
  'running',
  'completed',
  'failed',
] as const

export default function JobsPage() {
  const [statusFilter, setStatusFilter] = useState<string | undefined>(
    undefined,
  )
  const { data: activeJobs } = useActiveJobCount()
  const drain = useDrainJobs()

  const hasActive = (activeJobs?.running ?? 0) + (activeJobs?.pending ?? 0) > 0
  const hasPending = (activeJobs?.pending ?? 0) > 0

  function handleStatusFilter(s: string) {
    setStatusFilter(s || undefined)
  }

  return (
    <>
      <PageHeader
        title="Runs"
        description={
          hasActive ? (
            <span className="text-xs text-accent flex items-center gap-1">
              <span className="animate-spin inline-block">↻</span> live
            </span>
          ) : (
            'Workflow run history'
          )
        }
        action={
          <Button
            size="sm"
            variant={hasPending ? 'primary' : 'default'}
            onClick={() => drain.mutate()}
            disabled={drain.isPending}
          >
            {drain.isPending ? '↻ Running…' : 'Run automation'}
          </Button>
        }
      />

      <div className="flex items-center gap-2 mb-3">
        {STATUS_OPTIONS.map((s) => (
          <button
            key={s || 'all'}
            onClick={() => handleStatusFilter(s)}
            className={`px-3 py-2 text-xs rounded-full border transition-colors ${
              (statusFilter ?? '') === s
                ? 'bg-accent text-white border-accent'
                : 'bg-white text-fg-muted border-border hover:bg-canvas-subtle'
            }`}
          >
            {s || 'All'}
          </button>
        ))}
      </div>

      <JobsTable statusFilter={statusFilter} />
    </>
  )
}
