import { Link } from 'react-router-dom'
import { useJobs, useDrainJobs, useRerunJob } from '../../hooks/useWorkflows'
import { type WorkflowJob } from '../../api/workflows'
import { PageHeader, LoadingState, ErrorState, EmptyState, Badge, Button } from '../../components/ui'

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

interface Props {
    recordId?: string
}

export default function JobsTable({recordId}: Props) {
  const { data: jobs, isLoading, error } = useJobs(undefined, recordId)
  const drain = useDrainJobs()
  const rerun = useRerunJob()
  const hasActive = jobs?.some(j => j.status === 'pending' || j.status === 'running')
  const hasPending = jobs?.some(j => j.status === 'pending')

  if (isLoading) return <LoadingState />
  if (error)     return <ErrorState message={error.message} />

  return (
    <>
      {!jobs?.length ? (
        <EmptyState title="No jobs yet" message="Run a workflow from the Workflows page." />
      ) : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-[#d0d7de]">
              <th className="text-left py-2 px-3 font-medium text-[#1f2328]">Job</th>
              <th className="text-left py-2 px-3 font-medium text-[#1f2328]">Workflow</th>
              <th className="text-left py-2 px-3 font-medium text-[#1f2328]">Record</th>
              <th className="text-left py-2 px-3 font-medium text-[#1f2328]">Schema</th>
              <th className="text-left py-2 px-3 font-medium text-[#1f2328]">Trigger</th>
              <th className="text-left py-2 px-3 font-medium text-[#1f2328]">Status</th>
              <th className="text-left py-2 px-3 font-medium text-[#1f2328]">Duration</th>
              <th className="text-left py-2 px-3 font-medium text-[#1f2328]">Created</th>
              <th className="py-2 px-3" />
            </tr>
          </thead>
          <tbody>
            {jobs.map(job => (
              <>
                <tr key={job.id} className="border-b border-[#d0d7de] hover:bg-[#f6f8fa]">
                  <td className="py-2 px-3">
                    <Link to={`/jobs/${job.id}`} className="font-mono text-xs text-[#0969da] hover:underline">
                      {job.id.slice(0, 8)}…
                    </Link>
                  </td>
                  <td className="py-2 px-3 font-medium text-[#1f2328]">{job.workflow_name}</td>
                  <td className="py-2 px-3">
                    <Link to={`/records/${job.record_id}`} className="font-mono text-xs text-[#0969da] hover:underline">
                      {job.record_id.slice(0, 8)}…
                    </Link>
                  </td>
                  <td className="py-2 px-3 text-[#656d76]">{job.schema_name}</td>
                  <td className="py-2 px-3">
                    <Badge variant="default">{job.trigger}</Badge>
                  </td>
                  <td className="py-2 px-3"><StatusBadge status={job.status} /></td>
                  <td className="py-2 px-3 text-[#656d76]">{duration(job)}</td>
                  <td className="py-2 px-3 text-[#656d76] text-xs">
                    {new Date(job.created_at).toLocaleTimeString()}
                  </td>
                  <td className="py-2 px-3 text-right">
                    <Button
                      size="sm"
                      variant="default"
                      disabled={rerun.isPending}
                      onClick={() => rerun.mutate(job.id)}
                    >
                      ↻
                    </Button>
                  </td>
                </tr>
                {job.status === 'failed' && job.error && (
                  <tr key={`${job.id}-err`} className="border-b border-[#d0d7de] bg-red-50">
                    <td colSpan={9} className="py-1.5 px-3 text-xs text-red-700 font-mono">
                      {job.error}
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}
