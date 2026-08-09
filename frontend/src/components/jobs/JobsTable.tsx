import { useState } from 'react'
import { Link } from 'react-router'
import { useJobsPaged, useRerunJob } from '../../hooks/useWorkflows'
import { type WorkflowJob } from '../../api/workflows'
import { TableSkeleton, ErrorState, Badge, Button, Pagination } from '../ui'
import { RefreshCw } from '../ui/icons'
import JobStatusBadge from './JobStatusBadge'
import { explainFailure, summarizeRun } from '../../utils/runNarrative'

const RUN_COLUMNS = [
  'w-20',
  'w-32',
  'w-40',
  'w-20',
  'w-24',
  'w-16',
  'w-16',
  'w-24',
]
const RUN_COLUMNS_WITH_RECORD = [
  'w-20',
  'w-32',
  'w-40',
  'w-20',
  'w-20',
  'w-24',
  'w-16',
  'w-16',
  'w-24',
]

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

  if (isLoading)
    return (
      <TableSkeleton
        bordered={false}
        columns={recordId ? RUN_COLUMNS_WITH_RECORD : RUN_COLUMNS}
        rows={8}
      />
    )
  if (error) return <ErrorState message={error.message} />

  if (!jobs.data?.length) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex flex-col items-center justify-center py-16 text-center"
      >
        <svg
          width="40"
          height="40"
          viewBox="0 0 16 16"
          fill="none"
          className="mb-4 text-border"
          aria-hidden
        >
          <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" />
          <path
            d="M5.5 8l2 2 3-3"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <h2 className="text-lg font-semibold text-fg mb-2">No runs yet</h2>
        <p className="text-sm text-fg-muted max-w-sm">
          Workflow runs appear here when a workflow is triggered. Trigger a
          workflow manually from the Workflows tab.
        </p>
      </div>
    )
  }

  return (
    <div aria-busy={isFetching}>
      {liveRegion}
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-border">
            <th className="text-left py-2 px-3 font-medium text-fg">Run</th>
            <th className="text-left py-2 px-3 font-medium text-fg">
              Workflow
            </th>
            {!recordId && (
              <th className="text-left py-2 px-3 font-medium text-fg">
                Record
              </th>
            )}
            <th className="text-left py-2 px-3 font-medium text-fg">
              What happened
            </th>
            <th className="text-left py-2 px-3 font-medium text-fg">Schema</th>
            <th className="text-left py-2 px-3 font-medium text-fg">Trigger</th>
            <th className="text-left py-2 px-3 font-medium text-fg">Status</th>
            <th className="text-left py-2 px-3 font-medium text-fg">
              Duration
            </th>
            <th className="text-left py-2 px-3 font-medium text-fg">Created</th>
            <th className="py-2 px-3" />
          </tr>
        </thead>
        <tbody>
          {jobs.data.map((job) => (
            <tr
              key={job.id}
              className="border-b border-border hover:bg-canvas-subtle"
            >
              <td className="py-2 px-3">
                <Link
                  to={`/runs/${job.id}`}
                  className="font-mono text-xs text-accent hover:underline"
                >
                  {job.id.slice(0, 8)}…
                </Link>
              </td>
              <td className="py-2 px-3 font-medium text-fg">
                {job.workflow_name}
              </td>
              {!recordId && (
                <td className="py-2 px-3">
                  <Link
                    to={`/records/${job.record_id}`}
                    className="font-mono text-xs text-accent hover:underline"
                  >
                    {job.record_id.slice(0, 8)}…
                  </Link>
                </td>
              )}
              <td className="py-2 px-3">
                <WhatHappened job={job} />
              </td>
              <td className="py-2 px-3 text-fg-muted">{job.schema_name}</td>
              <td className="py-2 px-3">
                <Badge variant="default">{job.trigger}</Badge>
              </td>
              <td className="py-2 px-3">
                <JobStatusBadge status={job.status} />
              </td>
              <td className="py-2 px-3 text-fg-muted">{duration(job)}</td>
              <td className="py-2 px-3 text-fg-muted text-xs">
                {new Date(job.created_at).toLocaleString()}
              </td>
              <td className="py-2 px-3 text-right">
                <Button
                  size="sm"
                  variant="default"
                  disabled={rerun.isPending}
                  onClick={() => rerun.mutate(job.id)}
                  title="Rerun"
                >
                  <RefreshCw size={12} />
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
