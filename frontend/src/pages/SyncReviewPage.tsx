import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import type {
  ConflictTake,
  ResolveManyResult,
  SyncConflict,
} from '../api/remote'
import { ConflictSubject } from '../components/sync/ConflictSubject'
import {
  byWhom,
  inReviewOrder,
  kindLabel,
  takeLabel,
} from '../utils/syncConflicts'
import { saveReview, stepsFrom } from '../utils/reviewSession'
import {
  Button,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorState,
  Page,
  Select,
  Skeleton,
} from '../components/ui'
import { AuditValue } from '../components/audit/AuditValue'
import {
  useReopenConflicts,
  useRemoteStatus,
  useResolveConflict,
  useResolveMany,
  useSyncConflicts,
} from '../hooks/useRemote'
import { errorMessage } from '../lib/errors'
import { formatDate } from '../lib/utils'

/** What can be taken back: only "keep theirs" changed nothing, so only it. */
interface Undo {
  ids: string[]
  text: string
}

/** What a row's change is, in a word. */
function what(c: SyncConflict): string {
  return c.kind === 'conflict'
    ? (c.field_label ?? c.field ?? '')
    : kindLabel(c.kind)
}

/** A thing with no record page to settle it on (a schema's refused change, a
 * record that is gone) is settled in its row. */
function RowActions({ conflict: c }: { conflict: SyncConflict }) {
  const resolve = useResolveConflict()
  if (c.entity_type === 'record' && !c.record_deleted)
    return (
      <Button size="sm" to={`/records/${c.entity_id}?tab=resolve`}>
        Resolve
      </Button>
    )
  const choices = c.takes.filter((t) => t !== 'value' && t !== 'edited')
  return (
    <span className="flex flex-wrap gap-1">
      {choices.map((t: ConflictTake) => (
        <Button
          key={t}
          size="sm"
          disabled={resolve.isPending}
          onClick={() => resolve.mutate({ id: c.id, take: t })}
        >
          {takeLabel(c.kind, t)}
        </Button>
      ))}
      {resolve.error && (
        <span role="alert" className="text-xs text-danger">
          {errorMessage(resolve.error)}
        </span>
      )}
    </span>
  )
}

/** Everything that did not go in as made, as an inbox: what it is, which record,
 * and a way in. Records are settled on their own page (the merge view), and
 * **Start review** steps through them one record at a time; what is here is the
 * overview, narrowing by kind, and settling many at once. Settling any of them is
 * an ordinary edit, so nothing here can lose a value. */
export default function SyncReviewPage() {
  const { data, isLoading, error } = useSyncConflicts(true)
  const { data: status } = useRemoteStatus()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const kind = params.get('kind')
  const all = useMemo(() => inReviewOrder(data ?? []), [data])
  const items = useMemo(
    () => (kind ? all.filter((c) => c.kind === kind) : all),
    [all, kind],
  )
  const kinds = useMemo(() => {
    const counts = new Map<string, number>()
    for (const c of all) counts.set(c.kind, (counts.get(c.kind) ?? 0) + 1)
    return [...counts]
  }, [all])

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [settled, setSettled] = useState(0)
  const [undo, setUndo] = useState<Undo | null>(null)
  const [confirming, setConfirming] = useState(false)
  const many = useResolveMany()
  const count = useResolveMany()
  const bulk = useResolveMany()
  const reopen = useReopenConflicts()

  const chosen = items.filter((c) => selected.has(c.id))
  // What each bulk button can do: only the rows that offer it.
  const can = (take: ConflictTake) =>
    chosen.filter((c) => c.takes.includes(take))

  const setKind = (next: string | null) =>
    setParams(
      (p) => {
        const q = new URLSearchParams(p)
        if (next) q.set('kind', next)
        else q.delete('kind')
        return q
      },
      { replace: true },
    )

  const noted = (r: ResolveManyResult, take: ConflictTake) => {
    setSettled((s) => s + r.done)
    // Only "keep theirs" changed nothing, so only it can be taken back here;
    // the rest are ordinary edits, undone from Activity.
    setUndo(
      take === 'theirs' && r.settled_ids.length > 0
        ? {
            ids: r.settled_ids,
            text: `Kept theirs for ${r.done} change${r.done === 1 ? '' : 's'}.`,
          }
        : null,
    )
  }

  const runSelected = (take: 'theirs' | 'mine') =>
    many.mutate(
      { ids: can(take).map((c) => c.id), take },
      {
        onSuccess: (r) => {
          setSelected(new Set())
          noted(r, take)
        },
      },
    )

  const startReview = () => {
    const steps = stepsFrom(items)
    if (steps.length === 0) return
    saveReview(steps)
    navigate(`/records/${steps[0].id}?tab=resolve`)
  }

  // A bulk action covers what the filter shows, all of it, not only what is loaded.
  const scope = { kind: kind ?? undefined }
  const startBulk = () => {
    bulk.reset()
    setConfirming(true)
    count.mutate({ take: 'theirs', ...scope, dry_run: true })
  }
  const shownOfAll =
    status && status.open_conflicts > all.length
      ? `Showing the newest ${all.length} of ${status.open_conflicts}; settling these makes room for the rest.`
      : null
  const records = stepsFrom(items).length

  return (
    <Page
      breadcrumbs={[
        { label: 'Settings', to: '/settings' },
        { label: 'Sync', to: '/settings/sync' },
        { label: 'Review' },
      ]}
      title="Review sync conflicts"
      info="Values that did not go in as you made them. The other side’s value was kept and yours is saved. Open a record to settle it side by side; choosing is an ordinary edit, so it is checked, appears in the history and syncs."
      action={
        records > 0 && (
          <Button variant="primary" onClick={startReview}>
            Start review{records > 1 ? ` (${records} records)` : ''}
          </Button>
        )
      }
    >
      {undo && (
        <div
          role="status"
          className="mb-3 flex max-w-3xl flex-wrap items-center gap-2 rounded-md border border-border bg-canvas-subtle px-3 py-2 text-sm"
        >
          <span>{undo.text}</span>
          <Button
            size="sm"
            variant="link"
            disabled={reopen.isPending}
            onClick={() =>
              reopen.mutate(undo.ids, {
                onSuccess: (r) => {
                  setSettled((s) => Math.max(0, s - r.reopened))
                  setUndo(null)
                },
              })
            }
          >
            Undo
          </Button>
          <Button size="sm" variant="link" onClick={() => setUndo(null)}>
            Dismiss
          </Button>
          {reopen.error && (
            <span role="alert" className="text-danger">
              {errorMessage(reopen.error)}
            </span>
          )}
        </div>
      )}

      {all.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {kinds.length > 1 && (
            <Select
              size="sm"
              aria-label="Show"
              value={kind ?? ''}
              onChange={(e) => setKind(e.target.value || null)}
            >
              <option value="">All ({all.length})</option>
              {kinds.map(([k, n]) => (
                <option key={k} value={k}>
                  {kindLabel(k)} ({n})
                </option>
              ))}
            </Select>
          )}
          <Button size="sm" onClick={startBulk} disabled={items.length === 0}>
            {kind ? 'Keep theirs for these' : 'Keep theirs for all'}
          </Button>
          <span className="text-sm text-fg-muted">
            {chosen.length} selected
          </span>
          {(['theirs', 'mine'] as const).map((take) => (
            <Button
              key={take}
              size="sm"
              disabled={many.isPending || can(take).length === 0}
              onClick={() => runSelected(take)}
            >
              {takeLabel('conflict', take)}
              {chosen.length > 0 && ` (${can(take).length})`}
            </Button>
          ))}
          {settled > 0 && (
            <span className="text-sm text-fg-muted">
              {settled} settled · {all.length} left
            </span>
          )}
        </div>
      )}
      {many.data && many.data.failed.length > 0 && (
        <p role="alert" className="mb-3 text-sm text-danger">
          {many.data.failed.length} could not be settled and stay open (for
          example, a value that changed again since):{' '}
          {many.data.failed[0].message}
        </p>
      )}
      {many.error && (
        <p role="alert" className="mb-3 text-sm text-danger">
          {errorMessage(many.error)}
        </p>
      )}
      {shownOfAll && <p className="mb-3 text-xs text-fg-muted">{shownOfAll}</p>}

      {isLoading ? (
        <Skeleton className="h-40 w-full max-w-3xl" />
      ) : error ? (
        <ErrorState message={errorMessage(error)} />
      ) : all.length === 0 ? (
        <EmptyState
          title="Nothing to review"
          message="Everything you changed went in as you made it."
        />
      ) : items.length === 0 ? (
        <EmptyState
          title="Nothing here"
          message="Nothing is left of this kind."
          action={
            <Button size="sm" onClick={() => setKind(null)}>
              Show all
            </Button>
          }
        />
      ) : (
        <DataTable
          rows={items}
          getRowId={(c) => c.id}
          selection={{
            selected,
            onToggle: (id) =>
              setSelected((s) => {
                const next = new Set(s)
                if (!next.delete(id)) next.add(id)
                return next
              }),
            onSetMany: (ids, on) =>
              setSelected((s) => {
                const next = new Set(s)
                for (const id of ids) {
                  if (on) next.add(id)
                  else next.delete(id)
                }
                return next
              }),
            onToggleAll: () =>
              setSelected((s) =>
                s.size === items.length
                  ? new Set()
                  : new Set(items.map((c) => c.id)),
              ),
            rowLabel: (id) =>
              `Select ${items.find((c) => c.id === id)?.record_name ?? id}`,
          }}
          columns={[
            {
              key: 'record',
              header: 'Record',
              render: (c) => <ConflictSubject conflict={c} />,
            },
            { key: 'what', header: 'What', render: what },
            {
              key: 'yours',
              header: 'Yours',
              render: (c) =>
                c.kind === 'conflict' ? (
                  <AuditValue value={c.yours} dtype={c.dtype} compact />
                ) : null,
            },
            {
              key: 'theirs',
              header: 'Kept',
              render: (c) =>
                c.kind === 'conflict' ? (
                  <span>
                    <AuditValue value={c.theirs} dtype={c.dtype} compact />
                    {c.theirs_actor && (
                      <span className="text-fg-muted">
                        {' '}
                        · {byWhom(c.theirs_actor, c.theirs_device)}
                      </span>
                    )}
                  </span>
                ) : (
                  <span className="text-fg-muted">{c.message}</span>
                ),
            },
            {
              key: 'when',
              header: 'When',
              render: (c) => formatDate(c.created_at),
            },
            {
              key: 'act',
              header: '',
              render: (c) => <RowActions conflict={c} />,
            },
          ]}
        />
      )}

      {confirming && (
        <ConfirmDialog
          title={kind ? 'Keep theirs for these?' : 'Keep theirs for all?'}
          body={
            count.error ? (
              errorMessage(count.error)
            ) : !count.data ? (
              'Counting…'
            ) : count.data.done === 0 ? (
              'There is nothing to settle this way.'
            ) : (
              <>
                <p>
                  Keep the other side’s value for {count.data.done}{' '}
                  {count.data.done === 1 ? 'change' : 'changes'}? Your data
                  doesn’t change: your own values are let go.
                </p>
                {count.data.not_offered > 0 && (
                  <p className="mt-2 text-fg-muted">
                    {count.data.not_offered} can’t be settled this way and stay
                    open.
                  </p>
                )}
                <p className="mt-2 text-fg-muted">
                  You can undo it straight afterwards.
                </p>
              </>
            )
          }
          confirmLabel={
            count.data && count.data.done > 0
              ? `Keep theirs for ${count.data.done}`
              : 'Keep theirs'
          }
          confirmDisabled={!count.data || count.data.done === 0}
          isPending={bulk.isPending}
          warning={bulk.error ? errorMessage(bulk.error) : undefined}
          onConfirm={() =>
            bulk.mutate(
              { take: 'theirs', ...scope },
              {
                onSuccess: (r) => {
                  setConfirming(false)
                  noted(r, 'theirs')
                },
              },
            )
          }
          onClose={() => setConfirming(false)}
        />
      )}
    </Page>
  )
}
