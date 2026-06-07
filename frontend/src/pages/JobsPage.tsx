import { Link } from 'react-router-dom'
import { useJobs, useDrainJobs, useRerunJob } from '../hooks/useWorkflows'
import { type WorkflowJob } from '../api/workflows'
import { PageHeader, LoadingState, ErrorState, EmptyState, Badge, Button } from '../components/ui'
import JobsTable from '../components/jobs/JobsTable'

function duration(job: WorkflowJob): string {
  if (!job.started_at) return '—'
  const end = job.finished_at ? new Date(job.finished_at) : new Date()
  const secs = (end.getTime() - new Date(job.started_at).getTime()) / 1000
  return secs < 60 ? `${secs.toFixed(1)}s` : `${(secs / 60).toFixed(1)}m`
}

function StatusBadge({ status }: { status: WorkflowJob['status'] }) {
  switch (status) {
    case 'completed': return <Badge variant="success">✓ completed</Badge>
    case 'failed':    return <Badge variant="danger">✗ failed</Badge>
    case 'running':   return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-[#0969da]">
        <span className="animate-spin">↻</span> running
      </span>
    )
    default: return <Badge variant="default">· pending</Badge>
  }
}

export default function JobsPage() {
  const { data: jobs, isLoading, error } = useJobs()
  const drain = useDrainJobs()
  const rerun = useRerunJob()
  const hasActive = jobs?.some(j => j.status === 'pending' || j.status === 'running')
  const hasPending = jobs?.some(j => j.status === 'pending')

  if (isLoading) return <LoadingState />
  if (error)     return <ErrorState message={error.message} />

  return (
    <>
      <PageHeader
        title="Jobs"
        description={
          hasActive
            ? <span className="text-xs text-[#0969da] flex items-center gap-1"><span className="animate-spin inline-block">↻</span> live</span>
            : 'Workflow job history'
        }
        action={
          <Button
            size="sm"
            variant={hasPending ? 'primary' : 'default'}
            onClick={() => drain.mutate()}
            disabled={drain.isPending}
          >
            {drain.isPending ? '↻ Running…' : 'Run worker'}
          </Button>
        }
      />
      <JobsTable />
    </>
  )
}
