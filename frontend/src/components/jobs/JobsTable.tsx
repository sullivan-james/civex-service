import { useState } from 'react'
import { Link } from 'react-router'
import { useJobsPaged, useRerunJob } from '../../hooks/useWorkflows'
import { type WorkflowJob } from '../../api/workflows'
import { DataTable, type DataTableColumn, Badge, Button, Pagination } from '../ui'
import { Check, XCircle, RefreshCw, Clock } from '../ui/icons'

function duration(job: WorkflowJob): string {
  if (!job.started_at) return '—'
  const end = job.finished_at ? new Date(job.finished_at) : new Date()
  const secs = (end.getTime() - new Date(job.started_at).getTime()) / 1000
  return secs < 60 ? `${secs.toFixed(1)}s` : `${(secs / 60).toFixed(1)}m`
}

function StatusBadge({ status }: { status: WorkflowJob['status'] }) {
  switch (status) {
    case 'completed':
      return (
        <Badge variant="success" className="gap-1">
          <Check size={12} /> completed
        </Badge>
      )
    case 'failed':
      return (
        <Badge variant="danger" className="gap-1">
          <XCircle size={12} /> failed
        </Badge>
      )
    case 'running':
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-accent">
          <RefreshCw size={12} className="animate-spin" /> running
        </span>
      )
    default:
      return (
        <Badge variant="default" className="gap-1">
          <Clock size={12} /> pending
        </Badge>
      )
  }
}

interface Props {
  recordId?: string
  statusFilter?: string
}

export default function JobsTable({ recordId, statusFilter }: Props) {
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(25)

  // Reset to first page whenever filters change. Adjusted during render
  // (see https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes)
  // rather than in an effect -- avoids an extra render pass and the
  // react-hooks/set-state-in-effect lint rule.
  const [prevFilters, setPrevFilters] = useState([statusFilter, recordId])
  if (prevFilters[0] !== statusFilter || prevFilters[1] !== recordId) {
    setPrevFilters([statusFilter, recordId])
    setPage(0)
  }

  const { jobs, total, isLoading, error } = useJobsPaged(
    page,
    pageSize,
    statusFilter,
    recordId,
  )
  const rerun = useRerunJob()

  const columns: DataTableColumn<WorkflowJob>[] = [
    {
      key: 'run',
      header: 'Run',
      width: '96px',
      render: (job) => (
        <Link
          to={`/runs/${job.id}`}
          className="font-mono text-xs text-accent hover:underline"
        >
          {job.id.slice(0, 8)}…
        </Link>
      ),
    },
    {
      key: 'workflow_name',
      header: 'Workflow',
      render: (job) => (
        <span className="font-medium text-fg">{job.workflow_name}</span>
      ),
    },
    ...(recordId
      ? []
      : [
          {
            key: 'record_id',
            header: 'Record',
            render: (job: WorkflowJob) => (
              <Link
                to={`/records/${job.record_id}`}
                className="font-mono text-xs text-accent hover:underline"
              >
                {job.record_id.slice(0, 8)}…
              </Link>
            ),
          },
        ]),
    {
      key: 'schema_name',
      header: 'Schema',
      render: (job) => <span className="text-fg-muted">{job.schema_name}</span>,
    },
    {
      key: 'trigger',
      header: 'Trigger',
      render: (job) => <Badge variant="default">{job.trigger}</Badge>,
    },
    {
      key: 'status',
      header: 'Status',
      render: (job) => (
        <div className="flex flex-col items-start gap-0.5 whitespace-normal">
          <StatusBadge status={job.status} />
          {job.status === 'failed' && job.error && (
            <span className="whitespace-normal break-words text-xs text-danger font-mono">
              {job.error}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'duration',
      header: 'Duration',
      align: 'right',
      width: '96px',
      render: (job) => <span className="text-fg-muted">{duration(job)}</span>,
    },
    {
      key: 'created_at',
      header: 'Created',
      render: (job) => (
        <span className="text-fg-muted text-xs">
          {new Date(job.created_at).toLocaleString()}
        </span>
      ),
    },
  ]

  return (
    <>
      <DataTable
        columns={columns}
        rows={jobs.data ?? []}
        getRowId={(job) => job.id}
        isLoading={isLoading}
        error={error?.message}
        emptyTitle="No runs yet"
        emptyMessage="Workflow runs appear here when a workflow is triggered. Trigger a workflow manually from the Workflows tab."
        actions={(job) => (
          <Button
            size="sm"
            variant="default"
            disabled={rerun.isPending}
            onClick={() => rerun.mutate(job.id)}
            title="Rerun"
          >
            <RefreshCw size={12} />
          </Button>
        )}
        actionsLabel="Rerun"
        actionsWidth="64px"
      />
      <Pagination
        page={page}
        pageSize={pageSize}
        total={total}
        onPage={setPage}
        onPageSize={setPageSize}
      />
    </>
  )
}
