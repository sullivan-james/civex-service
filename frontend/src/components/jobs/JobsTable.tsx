import { useState } from 'react'
import { Link } from 'react-router'
import { useJobsPaged, useRerunJob } from '../../hooks/useWorkflows'
import { type WorkflowJob } from '../../api/workflows'
import {
  DataTable,
  type DataTableColumn,
  Badge,
  Button,
  Pagination,
} from '../ui'
import { RefreshCw } from '../ui/icons'
import JobStatusBadge from './JobStatusBadge'
import { explainFailure, summarizeRun } from '../../utils/runNarrative'

function duration(job: WorkflowJob): string {
  if (!job.started_at) return '—'
  const end = job.finished_at ? new Date(job.finished_at) : new Date()
  const secs = (end.getTime() - new Date(job.started_at).getTime()) / 1000
  return secs < 60 ? `${secs.toFixed(1)}s` : `${(secs / 60).toFixed(1)}m`
}

/** What this run did, condensed to fit a table cell. */
function WhatHappened({ job }: { job: WorkflowJob }) {
  if (job.status === 'failed') {
    return (
      <span className="text-danger">
        {explainFailure(job.error_details).headline}
      </span>
    )
  }
  if (job.status === 'pending' || job.status === 'running') {
    return <span className="text-fg-subtle">—</span>
  }
  const summary = summarizeRun(job)
  if (summary.length === 0) {
    return <span className="text-fg-subtle">No records created or changed</span>
  }
  return <span>{summary.join(', ')}</span>
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

  const { jobs, total, isLoading, isFetching, error } = useJobsPaged(
    page,
    pageSize,
    statusFilter,
    recordId,
  )
  const rerun = useRerunJob()

  // Announce a run's completion once, when it transitions out of
  // pending/running — not on every poll while it's still in flight. Detected
  // during render (see the prevFilters pattern above) rather than an effect,
  // so it settles in the same pass instead of scheduling an extra render.
  const [previousStatuses, setPreviousStatuses] = useState<
    Record<string, WorkflowJob['status']>
  >({})
  const [completionAnnouncement, setCompletionAnnouncement] = useState('')

  if (jobs.data) {
    const finished: WorkflowJob[] = []
    const nextStatuses: Record<string, WorkflowJob['status']> = {}
    for (const job of jobs.data) {
      nextStatuses[job.id] = job.status
      const prevStatus = previousStatuses[job.id]
      if (
        (prevStatus === 'pending' || prevStatus === 'running') &&
        (job.status === 'completed' || job.status === 'failed')
      ) {
        finished.push(job)
      }
    }
    if (
      jobs.data.some((job) => previousStatuses[job.id] !== job.status) ||
      Object.keys(previousStatuses).length !== jobs.data.length
    ) {
      setPreviousStatuses(nextStatuses)
    }
    if (finished.length === 1) {
      setCompletionAnnouncement(
        `${finished[0].workflow_name} ${finished[0].status}.`,
      )
    } else if (finished.length > 1) {
      const completed = finished.filter((j) => j.status === 'completed').length
      const failed = finished.filter((j) => j.status === 'failed').length
      const parts = []
      if (completed) parts.push(`${completed} completed`)
      if (failed) parts.push(`${failed} failed`)
      setCompletionAnnouncement(
        `${finished.length} runs finished: ${parts.join(', ')}.`,
      )
    }
  }

  const liveRegion = (
    <span role="status" aria-live="polite" className="sr-only">
      {completionAnnouncement}
    </span>
  )

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
      key: 'what_happened',
      header: 'What happened',
      render: (job) => <WhatHappened job={job} />,
    },
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
      render: (job) => <JobStatusBadge status={job.status} />,
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
    <div aria-busy={isFetching}>
      {liveRegion}
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
    </div>
  )
}
