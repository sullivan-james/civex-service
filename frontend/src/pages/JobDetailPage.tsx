import { Link, useNavigate, useParams } from 'react-router-dom'
import { useJob, useRerunJob } from '../hooks/useWorkflows'
import { type WorkflowJob } from '../api/workflows'
import { Badge, Button, LoadingState, ErrorState } from '../components/ui'

function StatusBadge({ status }: { status: WorkflowJob['status'] }) {
  switch (status) {
    case 'completed': return <Badge variant="success">✓ completed</Badge>
    case 'failed':    return <Badge variant="danger">✗ failed</Badge>
    case 'running':   return (
      <span className="inline-flex items-center gap-1 text-sm font-medium text-[#0969da]">
        <span className="animate-spin">↻</span> running
      </span>
    )
    default: return <Badge variant="default">· pending</Badge>
  }
}

function duration(job: WorkflowJob): string | null {
  if (!job.started_at) return null
  const end = job.finished_at ? new Date(job.finished_at) : new Date()
  const secs = (end.getTime() - new Date(job.started_at).getTime()) / 1000
  return secs < 60 ? `${secs.toFixed(2)}s` : `${(secs / 60).toFixed(2)}m`
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: job, isLoading, error } = useJob(id ?? '')
  const rerun = useRerunJob()

  if (isLoading) return <LoadingState />
  if (error)     return <ErrorState message={error.message} />
  if (!job)      return <ErrorState message="Job not found" />

  const isActive = job.status === 'pending' || job.status === 'running'

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="text-sm text-[#656d76]">
        <Link to="/jobs" className="text-[#0969da] hover:underline">Jobs</Link>
        <span className="mx-2">/</span>
        <span className="font-mono">{job.id.slice(0, 8)}…</span>
      </nav>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[#1f2328]">{job.workflow_name}</h1>
          <p className="text-sm text-[#656d76] mt-0.5 font-mono">{job.id}</p>
        </div>
        <div className="flex items-center gap-2">
          {isActive && <span className="text-xs text-[#0969da] animate-pulse">live</span>}
          <StatusBadge status={job.status} />
          <Button
            size="sm"
            disabled={rerun.isPending}
            onClick={() =>
              rerun.mutateAsync(job.id).then(newJob => navigate(`/jobs/${newJob.id}`))
            }
          >
            {rerun.isPending ? '↻ Re-running…' : '↻ Re-run'}
          </Button>
        </div>
      </div>

      {/* Metadata grid */}
      <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm border border-[#d0d7de] rounded-md p-4 bg-[#f6f8fa]">
        <div>
          <dt className="text-[#656d76] font-medium">Record</dt>
          <dd>
            <Link to={`/records/${job.record_id}`} className="font-mono text-[#0969da] hover:underline text-xs">
              {job.record_id.slice(0, 8)}…
            </Link>
          </dd>
        </div>
        <div>
          <dt className="text-[#656d76] font-medium">Schema</dt>
          <dd className="text-[#1f2328]">{job.schema_name}</dd>
        </div>
        <div>
          <dt className="text-[#656d76] font-medium">Trigger</dt>
          <dd><Badge variant="default">{job.trigger}</Badge></dd>
        </div>
        <div>
          <dt className="text-[#656d76] font-medium">Duration</dt>
          <dd className="text-[#1f2328]">{duration(job) ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-[#656d76] font-medium">Created</dt>
          <dd className="text-[#1f2328]">{new Date(job.created_at).toLocaleString()}</dd>
        </div>
        {job.finished_at && (
          <div>
            <dt className="text-[#656d76] font-medium">Finished</dt>
            <dd className="text-[#1f2328]">{new Date(job.finished_at).toLocaleString()}</dd>
          </div>
        )}
      </dl>

      {/* Error */}
      {job.error && (
        <div className="border border-red-200 rounded-md bg-red-50 p-4">
          <h2 className="text-sm font-semibold text-red-700 mb-1">Error</h2>
          <pre className="text-xs text-red-700 whitespace-pre-wrap font-mono">{job.error}</pre>
        </div>
      )}

      {/* Log output */}
      <div>
        <h2 className="text-sm font-semibold text-[#1f2328] mb-2">
          Output log
          {isActive && <span className="ml-2 text-xs font-normal text-[#0969da] animate-pulse">updating…</span>}
        </h2>
        {job.log ? (
          <pre className="text-xs font-mono bg-[#1c2128] text-[#adbac7] rounded-md p-4 overflow-auto max-h-[60vh] whitespace-pre-wrap leading-relaxed">
            {job.log}
          </pre>
        ) : (
          <div className="border border-dashed border-[#d0d7de] rounded-md p-6 text-sm text-center text-[#656d76]">
            {isActive ? 'Waiting for output…' : 'No output captured.'}
          </div>
        )}
      </div>
    </div>
  )
}
