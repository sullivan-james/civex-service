import { useState } from 'react'
import { Link } from 'react-router'
import { useJobsPaged, useRerunJob } from '../../hooks/useWorkflows'
import { type WorkflowJob } from '../../api/workflows'
import { LoadingState, ErrorState, Badge, Button, Field, Select } from '../ui'
import { Check, XCircle, RefreshCw } from '../ui/icons'

const PAGE_SIZES = [25, 50, 100]

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
      return <Badge variant="default">· pending</Badge>
  }
}

function Pagination({
  page,
  pageSize,
  total,
  onPage,
  onPageSize,
}: {
  page: number
  pageSize: number
  total: number
  onPage: (p: number) => void
  onPageSize: (s: number) => void
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const from = total === 0 ? 0 : page * pageSize + 1
  const to = Math.min((page + 1) * pageSize, total)

  return (
    <div className="flex items-center justify-between mt-4 text-sm text-fg-muted">
      <span>{total === 0 ? 'No results' : `${from}–${to} of ${total}`}</span>
      <div className="flex items-center gap-3">
        <Field label="Rows" layout="inline">
          <Select
            size="sm"
            value={pageSize}
            onChange={(e) => {
              onPageSize(Number(e.target.value))
              onPage(0)
            }}
          >
            {PAGE_SIZES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        </Field>
        <div className="flex items-center gap-1">
          <button
            onClick={() => onPage(0)}
            disabled={page === 0}
            className="px-2 py-2 rounded-md border border-border text-xs bg-canvas disabled:opacity-40 hover:bg-canvas-subtle disabled:cursor-not-allowed"
            title="First page"
          >
            «
          </button>
          <button
            onClick={() => onPage(page - 1)}
            disabled={page === 0}
            className="px-2 py-2 rounded-md border border-border text-xs bg-canvas disabled:opacity-40 hover:bg-canvas-subtle disabled:cursor-not-allowed"
          >
            ‹ Prev
          </button>
          <span className="px-2 text-xs">
            {page + 1} / {totalPages}
          </span>
          <button
            onClick={() => onPage(page + 1)}
            disabled={page >= totalPages - 1}
            className="px-2 py-2 rounded-md border border-border text-xs bg-canvas disabled:opacity-40 hover:bg-canvas-subtle disabled:cursor-not-allowed"
          >
            Next ›
          </button>
          <button
            onClick={() => onPage(totalPages - 1)}
            disabled={page >= totalPages - 1}
            className="px-2 py-2 rounded-md border border-border text-xs bg-canvas disabled:opacity-40 hover:bg-canvas-subtle disabled:cursor-not-allowed"
            title="Last page"
          >
            »
          </button>
        </div>
      </div>
    </div>
  )
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

  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message={error.message} />

  if (!jobs.data?.length) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
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
    <>
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
            <>
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
                <td className="py-2 px-3 text-fg-muted">{job.schema_name}</td>
                <td className="py-2 px-3">
                  <Badge variant="default">{job.trigger}</Badge>
                </td>
                <td className="py-2 px-3">
                  <StatusBadge status={job.status} />
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
              {job.status === 'failed' && job.error && (
                <tr
                  key={`${job.id}-err`}
                  className="border-b border-border bg-danger-subtle"
                >
                  <td
                    colSpan={recordId ? 8 : 9}
                    className="py-2 px-3 text-xs text-danger font-mono"
                  >
                    {job.error}
                  </td>
                </tr>
              )}
            </>
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
    </>
  )
}
