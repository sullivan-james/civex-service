import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import type { ConflictTake, SyncConflict } from '../api/remote'
import { ConflictCard, ConflictSubject } from '../components/sync/ConflictCard'
import { takeLabel } from '../utils/syncConflicts'
import {
  Button,
  DataTable,
  EmptyState,
  ErrorState,
  Page,
  SegmentedControl,
  Skeleton,
} from '../components/ui'
import { AuditValue } from '../components/audit/AuditValue'
import { useResolveMany, useSyncConflicts } from '../hooks/useRemote'
import { errorMessage } from '../lib/errors'
import { formatDate } from '../lib/utils'

type Mode = 'step' | 'list'

/** A record's conflicts sit together, then oldest first. */
function inReviewOrder(list: SyncConflict[]): SyncConflict[] {
  return [...list].sort(
    (a, b) =>
      (a.record_name ?? a.entity_id).localeCompare(
        b.record_name ?? b.entity_id,
      ) || a.created_at.localeCompare(b.created_at),
  )
}

/** Whether a key press is for the page and not for a field being typed in. */
function forPage(e: KeyboardEvent): boolean {
  const el = e.target as HTMLElement | null
  return !(
    e.metaKey ||
    e.ctrlKey ||
    e.altKey ||
    el?.closest('input, textarea, select, [contenteditable="true"]')
  )
}

function Step({
  items,
  index,
  go,
}: {
  items: SyncConflict[]
  index: number
  go: (i: number) => void
}) {
  const current = items[index]
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!forPage(e)) return
      if (e.key === 'ArrowRight' && index < items.length - 1) go(index + 1)
      if (e.key === 'ArrowLeft' && index > 0) go(index - 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [index, items.length, go])

  return (
    <div className="max-w-3xl space-y-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm text-fg-muted" aria-live="polite">
          {index + 1} of {items.length}
        </span>
        <span className="flex gap-2">
          <Button
            size="sm"
            disabled={index === 0}
            onClick={() => go(index - 1)}
          >
            Previous
          </Button>
          <Button
            size="sm"
            disabled={index >= items.length - 1}
            onClick={() => go(index + 1)}
          >
            Next
          </Button>
        </span>
      </div>
      {/* Keyed, so a new one starts with no half-typed value from the last. */}
      <ConflictCard key={current.id} conflict={current} shortcuts />
      <p className="text-xs text-fg-muted">
        Keys: ← → to move, 1 and 2 for the first two buttons.
      </p>
    </div>
  )
}

function List({
  items,
  open,
}: {
  items: SyncConflict[]
  open: (id: string) => void
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const many = useResolveMany()
  const chosen = items.filter((c) => selected.has(c.id))
  // What each bulk button can do: only the rows that offer it.
  const can = (take: ConflictTake) =>
    chosen.filter((c) => c.takes.includes(take))
  const run = (take: ConflictTake) =>
    many.mutate(
      { ids: can(take).map((c) => c.id), take },
      { onSuccess: () => setSelected(new Set()) },
    )

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-fg-muted">{chosen.length} selected</span>
        {(['theirs', 'mine'] as const).map((take) => (
          <Button
            key={take}
            size="sm"
            disabled={many.isPending || can(take).length === 0}
            onClick={() => run(take)}
          >
            {takeLabel('conflict', take)}
            {chosen.length > 0 && ` (${can(take).length})`}
          </Button>
        ))}
      </div>
      {many.data && many.data.failed.length > 0 && (
        <p role="alert" className="text-sm text-danger">
          {many.data.failed.length} could not be settled and stay open (for
          example, a value that changed again since):{' '}
          {many.data.failed[0].message}
        </p>
      )}
      {many.error && (
        <p role="alert" className="text-sm text-danger">
          {errorMessage(many.error)}
        </p>
      )}
      <DataTable
        rows={items}
        getRowId={(c) => c.id}
        onRowClick={(c) => open(c.id)}
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
          {
            key: 'what',
            header: 'What',
            render: (c) =>
              c.kind === 'conflict'
                ? (c.field_label ?? c.field)
                : c.kind === 'rejected'
                  ? 'Refused'
                  : c.kind === 'edit_vs_delete'
                    ? 'Edited, deleted there'
                    : c.kind,
          },
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
                    <span className="text-fg-muted"> · {c.theirs_actor}</span>
                  )}
                </span>
              ) : null,
          },
          {
            key: 'when',
            header: 'When',
            render: (c) => formatDate(c.created_at),
          },
        ]}
      />
    </div>
  )
}

/** Everything that did not go in as made, to look at one at a time or as a list.
 * Settling any of them is an ordinary edit, so nothing here can lose a value. */
export default function SyncReviewPage() {
  const { data, isLoading, error } = useSyncConflicts(true)
  const [params, setParams] = useSearchParams()
  const mode: Mode = params.get('mode') === 'list' ? 'list' : 'step'
  const items = useMemo(() => inReviewOrder(data ?? []), [data])
  const index = Math.min(
    Math.max(Number(params.get('i')) || 0, 0),
    Math.max(items.length - 1, 0),
  )

  const set = (next: Record<string, string | null>) =>
    setParams(
      (p) => {
        const q = new URLSearchParams(p)
        for (const [k, v] of Object.entries(next)) {
          if (v === null) q.delete(k)
          else q.set(k, v)
        }
        return q
      },
      { replace: true },
    )

  return (
    <Page
      breadcrumbs={[
        { label: 'Settings', to: '/settings' },
        { label: 'Sync', to: '/settings/sync' },
        { label: 'Review' },
      ]}
      title="Review sync conflicts"
      info="Values that did not go in as you made them. The other side’s value was kept and yours is saved here; choosing is an ordinary edit, so it is checked, appears in the history and syncs."
      action={
        items.length > 1 && (
          <SegmentedControl<Mode>
            label="View"
            value={mode}
            onChange={(m) => set({ mode: m === 'list' ? 'list' : null })}
            options={[
              { value: 'step', label: 'One at a time' },
              { value: 'list', label: 'List' },
            ]}
          />
        )
      }
    >
      {isLoading ? (
        <Skeleton className="h-40 w-full max-w-3xl" />
      ) : error ? (
        <ErrorState message={errorMessage(error)} />
      ) : items.length === 0 ? (
        <EmptyState
          title="Nothing to review"
          message="Everything you changed went in as you made it."
        />
      ) : mode === 'list' ? (
        <List
          items={items}
          open={(id) =>
            set({ mode: null, i: String(items.findIndex((c) => c.id === id)) })
          }
        />
      ) : (
        <Step items={items} index={index} go={(i) => set({ i: String(i) })} />
      )}
    </Page>
  )
}
