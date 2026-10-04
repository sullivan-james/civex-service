import { useState } from 'react'
import { Link } from 'react-router'
import { useListParams } from '../../hooks/useListParams'
import { useJobsPaged, useRerunJob } from '../../hooks/useWorkflows'
import { type WorkflowJob } from '../../api/workflows'
import {
  DataTable,
  type DataTableColumn,
  Badge,
  Button,
  ListToolbar,
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

const STATUSES = ['pending', 'running', 'completed', 'failed']
const TRIGGERS = ['record_created', 'record_updated', 'manual']
const anyOf = (values: string[]) => [
  { value: '', label: '' },
  ...values.map((v) => ({ value: v, label: v.replace('_', ' ') })),
]

interface Props {
  /** Only runs triggered by this record (the record page's Runs tab). */
  recordId?: string
  /** Prefix for this table's address parameters, when a page has more than
   * one list. */
  ns?: string
}

export default function JobsTable({ recordId, ns = '' }: Props) {
  const list = useListParams(ns, ['status', 'trigger'])
  const { jobs, total, isLoading, isFetching, error } = useJobsPaged(
    list.page,
    list.size,
    list.picks.status || undefined,
    recordId,
    {
      trigger: list.picks.trigger || undefined,
      search: list.q || undefined,
      sort: list.sortParam,
    },
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
      sortable: true,
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
      sortable: true,
      render: (job) => <span className="text-fg-muted">{job.schema_name}</span>,
    },
    {
      key: 'trigger',
      header: 'Trigger',
      sortable: true,
      render: (job) => <Badge variant="default">{job.trigger}</Badge>,
    },
    {
      key: 'status',
      header: 'Status',
      sortable: true,
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
      sortable: true,
      render: (job) => (
        <span className="text-fg-muted text-xs">
          {new Date(job.created_at).toLocaleString()}
        </span>
      ),
    },
  ]

  return (
    <div aria-busy={isFetching} className="space-y-3">
      {liveRegion}
      <ListToolbar
        search={{
          value: list.q,
          label: 'Search runs',
          onChange: (q) => list.set({ q }),
        }}
        picks={[
          {
            label: 'Any status',
            value: list.picks.status,
            options: anyOf(STATUSES),
            onChange: (status) => list.set({ status }),
          },
          {
            label: 'Any trigger',
            value: list.picks.trigger,
            options: anyOf(TRIGGERS),
            onChange: (trigger) => list.set({ trigger }),
          },
        ]}
      />
      <DataTable
        sort={
          list.sort
            ? { key: list.sort.field, direction: list.sort.dir }
            : undefined
        }
        onSortChange={list.toggleSort}
        columns={columns}
        rows={jobs.data ?? []}
        getRowId={(job) => job.id}
        isLoading={isLoading}
        error={error?.message}
        emptyTitle={
          list.q || list.picks.status || list.picks.trigger
            ? 'No runs match'
            : 'No runs yet'
        }
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
        page={list.page}
        pageSize={list.size}
        total={total}
        onPage={(page) => list.set({ page })}
        onPageSize={(size) => list.set({ size })}
      />
    </div>
  )
}
