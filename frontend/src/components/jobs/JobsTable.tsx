import { useCallback, useMemo, useState } from 'react'
import { useListParams } from '../../hooks/useListParams'
import { withRange } from '../../hooks/useRangeSelect'
import {
  useCancelJob,
  useFailureGroups,
  useJobsPaged,
  useRerunJob,
  useRerunJobs,
  useRunFilterFields,
  useWorkflows,
} from '../../hooks/useWorkflows'
import { useSchemas } from '../../hooks/useSchemas'
import {
  type FailureGroup,
  type RerunResult,
  type WorkflowJob,
} from '../../api/workflows'
import type { FilterTreeWire } from '../../utils/filterTree'
import { FilterControls } from '../explorer/FilterControls'
import { FailureGroups } from './FailureGroups'
import {
  RUN_LIST,
  allOf,
  failureGroupFilter,
  legacyRunFilter,
  runFilterFields,
  truncate,
  withCondition,
  withoutFields,
} from '../../utils/runFilter'
import {
  DataTable,
  type DataTableColumn,
  Badge,
  Button,
  ConfirmDialog,
  ListToolbar,
  Pagination,
} from '../ui'
import { RefreshCw, X } from '../ui/icons'
import { RecordLink } from '../records/RecordLink'
import JobStatusBadge from './JobStatusBadge'
import {
  LONG_CHAIN,
  causedBy,
  FAILURE_KINDS,
  explainFailure,
  runProblems,
  summarizeRun,
  watchedChanges,
} from '../../utils/runNarrative'

function duration(job: WorkflowJob): string {
  if (!job.started_at) return '—'
  const end = job.finished_at ? new Date(job.finished_at) : new Date()
  const secs = (end.getTime() - new Date(job.started_at).getTime()) / 1000
  return secs < 60 ? `${secs.toFixed(1)}s` : `${(secs / 60).toFixed(1)}m`
}

/** What this run did, condensed to a line under its status. */
function WhatHappened({ job }: { job: WorkflowJob }) {
  if (job.status === 'failed') {
    // The run's own message, cut to a line (the whole of it is the tooltip and
    // the run's page), with the step it came from: "an unexpected error" tells
    // a person nothing they can act on.
    const message = job.error_details?.message ?? job.error
    const step = job.error_details?.step
    return (
      <span className="block max-w-sm text-danger" title={message ?? undefined}>
        {message
          ? `${step ? `${step}: ` : ''}${truncate(message)}`
          : explainFailure(job.error_details).headline}
      </span>
    )
  }
  if (job.status === 'cancelled')
    return <span className="text-fg-subtle">Stopped</span>
  if (job.status === 'pending' || job.status === 'running') return null
  const summary = summarizeRun(job)
  return summary.length === 0 ? (
    <span className="text-fg-subtle">No records changed</span>
  ) : (
    <span>{summary.join(', ')}</span>
  )
}

/** When a run was made, and how long it took. */
function When({ job }: { job: WorkflowJob }) {
  return (
    <div className="whitespace-nowrap">
      <div className="text-xs text-fg-muted">
        {new Date(job.created_at).toLocaleString([], {
          dateStyle: 'short',
          timeStyle: 'short',
        })}
      </div>
      {job.started_at && (
        <div className="text-xs text-fg-subtle">{duration(job)}</div>
      )}
    </div>
  )
}

/** What started a run: the event, the field(s) that changed, and -- when
 * another run's save started it -- which workflow that was. */
function Trigger({ job }: { job: WorkflowJob }) {
  const fields = watchedChanges(job).map((c) => c.field)
  const cause = causedBy(job)
  return (
    <div className="flex flex-col items-start gap-0.5">
      <Badge variant="default">{job.trigger}</Badge>
      {fields.length > 0 && (
        <span className="font-mono text-xs text-fg-muted">
          {fields.join(', ')}
        </span>
      )}
      {cause && (
        <span
          className={`text-xs ${job.depth >= LONG_CHAIN ? 'text-attention' : 'text-fg-subtle'}`}
        >
          by {cause.workflow ?? 'another run'}
          {job.depth >= LONG_CHAIN && ` · chain of ${job.depth}`}
        </span>
      )}
    </div>
  )
}

interface Props {
  /** Only runs triggered by this record (the record page's Runs tab). */
  recordId?: string
  /** Prefix for this table's address parameters, when a page has more than
   * one list. */
  ns?: string
}

export default function JobsTable({ recordId, ns = '' }: Props) {
  // Filtering is the records explorer's: the same chips, the same builder,
  // over run fields, held in the address as `filter`. The old `status`,
  // `trigger` and `workflow` parameters still open, as the filter they mean.
  const list = useListParams(ns, ['filter', 'status', 'trigger', 'workflow'])
  const filter = useMemo<FilterTreeWire | null>(() => {
    if (list.picks.filter) {
      try {
        const parsed = JSON.parse(list.picks.filter)
        if (parsed && typeof parsed === 'object') return parsed
      } catch {
        /* a mangled address filters nothing */
      }
      return null
    }
    return legacyRunFilter(list.picks)
  }, [list.picks])
  const setFilter = (wire: FilterTreeWire | null) =>
    list.set({
      filter: wire ? JSON.stringify(wire) : '',
      status: '',
      trigger: '',
      workflow: '',
    })

  const { jobs, total, isLoading, isFetching, error } = useJobsPaged(
    list.page,
    list.size,
    undefined,
    recordId,
    { filter, search: list.q || undefined, sort: list.sortParam },
  )
  const rerun = useRerunJob()
  const rerunMany = useRerunJobs()
  const cancel = useCancelJob()
  const { data: workflows } = useWorkflows()
  const { data: schemas } = useSchemas()
  const { data: runFields } = useRunFilterFields()
  // The runs ticked for a bulk action. They stay ticked across pages until
  // acted on or cleared.
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [outcome, setOutcome] = useState<RerunResult | null>(null)
  const [confirmAll, setConfirmAll] = useState(false)

  const fields = useMemo(
    () =>
      runFilterFields(runFields, {
        workflow: [...new Set((workflows ?? []).map((w) => w.name))].sort(),
        schema: (schemas ?? []).map((s) => s.name).sort(),
        error_kind: [...FAILURE_KINDS].sort(),
      }),
    [runFields, workflows, schemas],
  )

  // On a record's page every count and every bulk action is about that record's
  // runs. The list is scoped by `recordId`; anything sent as a filter has to
  // say so itself, or it would reach every run in the project that matches.
  const recordScope = useMemo<FilterTreeWire | null>(
    () => (recordId ? { field: 'record', op: 'eq', value: recordId } : null),
    [recordId],
  )
  const scoped = useCallback(
    (wire: FilterTreeWire | null): FilterTreeWire | null =>
      allOf(...[recordScope, wire].filter((t): t is FilterTreeWire => !!t)),
    [recordScope],
  )

  // Why the runs in view failed, for whatever the filter covers.
  const { data: groups } = useFailureGroups(
    useMemo(() => scoped(filter), [scoped, filter]),
  )
  const lookingAtFailures = JSON.stringify(filter ?? {}).includes('"failed"')

  function done(result: RerunResult) {
    setOutcome(result)
    setSelected(new Set())
  }
  function rerunSelected() {
    rerunMany.mutate({ ids: [...selected] }, { onSuccess: done })
  }
  function rerunMatching(which: FilterTreeWire) {
    rerunMany.mutate({ filter: scoped(which)! }, { onSuccess: done })
  }
  // One failure group: its runs, alongside whatever else narrowed the list
  // (a time window, say), replacing what said otherwise about the same things.
  const groupScope = (g: FailureGroup) =>
    withCondition(
      withoutFields(filter, ['status', 'workflow', 'error_kind', 'error']),
      failureGroupFilter(g),
    )

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

  // Five columns, not nine: the run's own id and its schema are on the run
  // (the row opens it), the record's schema sits under its name, and the time
  // carries the duration.
  const columns: DataTableColumn<WorkflowJob>[] = [
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
              <div className="min-w-0">
                <RecordLink id={job.record_id} />
                <div className="text-xs text-fg-subtle">{job.schema_name}</div>
              </div>
            ),
          },
        ]),
    {
      key: 'trigger',
      header: 'Started by',
      sortable: true,
      render: (job) => <Trigger job={job} />,
    },
    {
      key: 'status',
      header: 'Result',
      sortable: true,
      render: (job) => (
        <div className="flex flex-col items-start gap-0.5">
          <JobStatusBadge
            status={job.status}
            problems={runProblems(job).total}
          />
          <span className="text-xs">
            <WhatHappened job={job} />
          </span>
        </div>
      ),
    },
    {
      key: 'created_at',
      header: 'When',
      sortable: true,
      render: (job) => <When job={job} />,
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
      />
      <FilterControls
        wire={filter}
        fields={fields}
        listedSchema={RUN_LIST}
        onChange={setFilter}
      />
      {groups && (
        <FailureGroups
          groups={groups}
          open={lookingAtFailures}
          rerunning={rerunMany.isPending}
          onShow={(g) => setFilter(groupScope(g))}
          onRerun={(g) => rerunMatching(groupScope(g))}
        />
      )}
      {filter && total > 0 && selected.size === 0 && (
        <div className="flex flex-wrap items-center gap-2 text-sm text-fg-muted">
          {total.toLocaleString()} {total === 1 ? 'run matches' : 'runs match'}
          <Button
            size="sm"
            disabled={rerunMany.isPending}
            onClick={() => setConfirmAll(true)}
          >
            <RefreshCw size={12} /> Re-run all {total.toLocaleString()}…
          </Button>
        </div>
      )}
      {confirmAll && filter && (
        <ConfirmDialog
          title={`Re-run ${total.toLocaleString()} ${total === 1 ? 'run' : 'runs'}`}
          body={
            <p>
              Queues a new run of each of the {total.toLocaleString()} runs that
              match this filter, on the same record with the same input.
              {total > 1000 && ' Only the newest 1,000 are queued at once.'}
            </p>
          }
          confirmLabel={`Re-run ${Math.min(total, 1000).toLocaleString()}`}
          isPending={rerunMany.isPending}
          onClose={() => setConfirmAll(false)}
          onConfirm={() => {
            rerunMatching(filter)
            setConfirmAll(false)
          }}
        />
      )}
      {selected.size > 0 && (
        <div
          role="region"
          aria-label="Bulk actions"
          className="flex flex-wrap items-center gap-3 rounded-md border border-accent-muted bg-accent-subtle px-4 py-2 text-sm"
        >
          <span className="font-medium text-fg">{selected.size} selected</span>
          <Button
            size="sm"
            variant="primary"
            disabled={rerunMany.isPending}
            onClick={rerunSelected}
          >
            <RefreshCw
              size={12}
              className={rerunMany.isPending ? 'animate-spin' : ''}
            />
            {rerunMany.isPending ? 'Re-running…' : `Re-run ${selected.size}`}
          </Button>
          <Button size="sm" onClick={() => setSelected(new Set())}>
            Clear selection
          </Button>
          {rerunMany.isError && (
            <span role="alert" className="text-xs text-danger">
              {rerunMany.error.message}
            </span>
          )}
        </div>
      )}
      {outcome && selected.size === 0 && (
        <p
          role="status"
          className="flex flex-wrap items-center gap-2 text-sm text-fg-muted"
        >
          Queued {outcome.started.length} run
          {outcome.started.length === 1 ? '' : 's'}.
          {outcome.skipped.length > 0 &&
            ` ${outcome.skipped.length} couldn't be repeated: ${[
              ...new Set(outcome.skipped.map((k) => k.reason)),
            ].join(' ')}`}
          <Button size="sm" variant="link" onClick={() => setOutcome(null)}>
            Dismiss
          </Button>
        </p>
      )}
      <DataTable
        dense
        layout="auto"
        // From a record's own Runs tab, the run remembers the record, so its
        // breadcrumb leads back up to it.
        rowHref={(job) =>
          recordId
            ? `/runs/${job.id}?from=${encodeURIComponent(recordId)}`
            : `/runs/${job.id}`
        }
        selection={{
          selected,
          onToggle: (id) =>
            setSelected((prev) => {
              const next = new Set(prev)
              if (next.has(id)) next.delete(id)
              else next.add(id)
              return next
            }),
          onSetMany: (ids, on) =>
            setSelected((prev) => withRange(prev, ids, on)),
          onToggleAll: () =>
            setSelected((prev) => {
              const shown = (jobs.data ?? []).map((j) => j.id)
              return shown.length > 0 && shown.every((id) => prev.has(id))
                ? new Set([...prev].filter((id) => !shown.includes(id)))
                : new Set([...prev, ...shown])
            }),
          allLabel: 'Select all runs on this page',
          rowLabel: (id) => {
            const job = (jobs.data ?? []).find((j) => j.id === id)
            return `Select the ${job?.workflow_name ?? ''} run`
          },
        }}
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
        emptyTitle={list.q || filter ? 'No runs match' : 'No runs yet'}
        actions={(job) => (
          <span className="inline-flex gap-1">
            {(job.status === 'pending' || job.status === 'running') && (
              <Button
                size="sm"
                variant="default"
                disabled={cancel.isPending}
                onClick={() => cancel.mutate(job.id)}
                title="Cancel this run"
                aria-label={`Cancel the ${job.workflow_name} run`}
              >
                <X size={12} />
              </Button>
            )}
            <Button
              size="sm"
              variant="default"
              disabled={rerun.isPending}
              onClick={() => rerun.mutate(job.id)}
              title="Rerun"
              aria-label={`Rerun ${job.workflow_name}`}
            >
              <RefreshCw size={12} />
            </Button>
          </span>
        )}
        actionsLabel="Actions"
        actionsWidth="96px"
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
