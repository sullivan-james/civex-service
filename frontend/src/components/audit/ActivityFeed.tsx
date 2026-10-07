import { useMemo, useState } from 'react'
import type { AuditEvent } from '../../api/audit'
import { useAuditEvents, useAuditFilterFields } from '../../hooks/useAudit'
import { useRestoreAll, useRestoreAllPlan } from '../../hooks/useRestore'
import type { RestoreTarget } from '../../api/restore'
import { useCollections } from '../../hooks/useCollections'
import { useSchemas } from '../../hooks/useSchemas'
import { useListParams } from '../../hooks/useListParams'
import { errorMessage } from '../../lib/errors'
import {
  AUDIT_LIST,
  auditFilterFields,
  isDeletedView,
  toggleDeleted,
  withScope,
} from '../../utils/auditFilter'
import { describeAuditEvent } from '../../utils/activityAudit'
import type { FilterTreeWire } from '../../utils/filterTree'
import { FilterControls } from '../explorer/FilterControls'
import {
  Badge,
  Button,
  ConfirmDialog,
  DataTable,
  ListToolbar,
  Pagination,
} from '../ui'
import { RestoreBatchDialog } from '../trash/RestoreBatchDialog'
import { RestoreDialog } from '../trash/RestoreDialog'
import { AuditEntryDialog } from './AuditEntryDialog'
import { BatchDialog } from './BatchDialog'
import { EntrySubject } from './EntrySubject'
import { SyncBadge } from './SyncOutcome'

type Variant = 'default' | 'accent' | 'success' | 'danger' | 'attention'

const ACTION_VARIANT: Record<string, Variant> = {
  create: 'success',
  update: 'accent',
  delete: 'danger',
  restore: 'accent',
  purge: 'danger',
}

const BATCH_LABEL: Record<string, string> = {
  import: 'import',
  delete: 'delete',
  restore: 'restore',
  purge: 'purge',
  workflow: 'workflow',
}

/** What became of the record an entry is about, said only when it is not
 * simply there: that is the part that explains something missing. */
function Now({ event }: { event: AuditEvent }) {
  const now = event.entry?.now
  if (!now || now.status === 'live') return null
  return (
    <Badge variant={now.status === 'deleted' ? 'attention' : 'danger'}>
      {now.status === 'deleted' ? 'Deleted now' : 'Gone for good'}
    </Badge>
  )
}

/**
 * History as events, filtered like the records explorer and the runs list: the
 * same chips and builder, held in the address as `filter`. A batch (an import,
 * a delete that took a tree, a workflow run) is one line however much it did.
 * `scope` is where the page already is (under this record, in this
 * collection); it always applies and is not shown as a chip.
 */
export function ActivityFeed({
  scope,
  ns = 'activity.',
  emptyMessage,
}: {
  scope?: FilterTreeWire | null
  ns?: string
  emptyMessage: string
}) {
  const list = useListParams(ns, ['filter'])
  const filter = useMemo<FilterTreeWire | null>(() => {
    if (!list.picks.filter) return null
    try {
      const parsed = JSON.parse(list.picks.filter)
      return parsed && typeof parsed === 'object' ? parsed : null
    } catch {
      return null // a mangled address filters nothing
    }
  }, [list.picks.filter])
  const setFilter = (wire: FilterTreeWire | null) =>
    list.set({ filter: wire ? JSON.stringify(wire) : '' })

  const { data: serverFields } = useAuditFilterFields()
  const { data: collections } = useCollections()
  const { data: schemas } = useSchemas()
  const fields = useMemo(
    () =>
      auditFilterFields(serverFields, {
        collection: (collections ?? []).map((c) => c.name).sort(),
        schema: (schemas ?? []).map((s) => s.name).sort(),
      }),
    [serverFields, collections, schemas],
  )

  const { data, isLoading, isFetching, error } = useAuditEvents(
    {
      filter: withScope(scope, filter),
      search: list.q || undefined,
      sort: list.sortParam,
    },
    list.page,
    list.size,
  )
  const [open, setOpen] = useState<AuditEvent | null>(null)
  const [restoring, setRestoring] = useState<RestoreTarget | null>(null)
  const [restoringBatch, setRestoringBatch] = useState<AuditEvent | null>(null)
  const [confirmAll, setConfirmAll] = useState(false)
  const narrowed = !!(filter || list.q)
  const deletedOn = isDeletedView(filter)
  const query = {
    filter: withScope(scope, filter),
    search: list.q || undefined,
  }
  const { data: plan } = useRestoreAllPlan(query, deletedOn)
  const restoreAll = useRestoreAll(() => setConfirmAll(false))

  return (
    <div aria-busy={isFetching} className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <ListToolbar
          search={{
            value: list.q,
            label: 'Search values, file names and labels',
            onChange: (q) => list.set({ q }),
          }}
        />
        <Button
          size="sm"
          variant={deletedOn ? 'primary' : 'default'}
          aria-pressed={deletedOn}
          onClick={() => setFilter(toggleDeleted(filter))}
        >
          Deleted
        </Button>
      </div>
      <FilterControls
        wire={filter}
        fields={fields}
        listedSchema={AUDIT_LIST}
        onChange={setFilter}
      />
      {deletedOn && plan && plan.things > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-sm text-fg-muted">
          {plan.things.toLocaleString()}{' '}
          {plan.things === 1 ? 'deleted thing matches' : 'deleted things match'}
          <Button size="sm" onClick={() => setConfirmAll(true)}>
            Restore all {plan.things.toLocaleString()}…
          </Button>
        </div>
      )}
      <DataTable
        layout="auto"
        sort={
          list.sort
            ? { key: list.sort.field, direction: list.sort.dir }
            : undefined
        }
        onSortChange={list.toggleSort}
        onRowClick={setOpen}
        actions={(e) => {
          // A bulk delete is one line: undo it as a whole from here, rather
          // than finding the parent among everything it took with it.
          if (e.batch?.kind === 'delete')
            return (
              <Button size="sm" onClick={() => setRestoringBatch(e)}>
                Restore
              </Button>
            )
          const now = e.entry?.now
          return e.entry?.action === 'delete' &&
            now?.status === 'deleted' &&
            now.ref ? (
            <Button
              size="sm"
              onClick={() =>
                setRestoring({
                  kind: now.kind,
                  ref: now.ref!,
                  schema: now.schema_name ?? undefined,
                })
              }
            >
              Restore
            </Button>
          ) : null
        }}
        actionsWidth="7rem"
        columns={[
          {
            key: 'actor',
            header: 'Who',
            width: '9rem',
            render: (e: AuditEvent) => {
              const who = e.actor ?? e.entry?.actor
              const via = e.device ?? e.entry?.device
              if (!who) return <span className="text-fg-subtle">—</span>
              return (
                <span className="flex flex-col">
                  <span className="truncate font-medium text-fg">{who}</span>
                  {via && via !== who && (
                    <span
                      className="truncate text-xs text-fg-muted"
                      title={`Sent from the device '${via}' (the server checked its token)`}
                    >
                      via {via}
                    </span>
                  )}
                </span>
              )
            },
          },
          {
            key: 'event',
            header: 'What happened',
            render: (e) => {
              const { title, detail } = describeAuditEvent(e)
              return (
                <div className="flex flex-col gap-0.5">
                  <span className="flex flex-wrap items-center gap-2">
                    <Badge
                      variant={
                        ACTION_VARIANT[
                          e.entry?.action ?? e.batch?.kind ?? ''
                        ] ?? 'default'
                      }
                    >
                      {e.entry ? e.entry.action : BATCH_LABEL[e.batch!.kind]}
                    </Badge>
                    {title}
                    <Now event={e} />
                    {e.entry && <SyncBadge entry={e.entry} />}
                  </span>
                  {e.entry && <EntrySubject entry={e.entry} />}
                  {detail && (
                    <span className="text-xs text-fg-muted">{detail}</span>
                  )}
                </div>
              )
            },
          },
          {
            key: 'timestamp',
            header: 'When',
            sortable: true,
            width: '12rem',
            className: 'text-fg-muted whitespace-nowrap',
            render: (e: AuditEvent) => new Date(e.timestamp).toLocaleString(),
          },
        ]}
        rows={data?.items ?? []}
        getRowId={(e) => e.id}
        isLoading={isLoading}
        error={error ? errorMessage(error) : undefined}
        emptyTitle={narrowed ? 'Nothing matches' : 'No history yet'}
        emptyMessage={narrowed ? undefined : emptyMessage}
      />
      {data && data.items.length > 0 && (
        <Pagination
          page={list.page}
          pageSize={list.size}
          total={data.total}
          onPage={(page) => list.set({ page })}
          onPageSize={(size) => list.set({ size })}
        />
      )}
      {open?.entry && (
        <AuditEntryDialog
          entry={open.entry}
          title={describeAuditEvent(open).title}
          onClose={() => setOpen(null)}
        />
      )}
      {restoring && (
        <RestoreDialog target={restoring} onClose={() => setRestoring(null)} />
      )}
      {restoringBatch && (
        <RestoreBatchDialog
          batchId={restoringBatch.batch!.id}
          onClose={() => setRestoringBatch(null)}
          onChoose={() => {
            setOpen(restoringBatch)
            setRestoringBatch(null)
          }}
        />
      )}
      {confirmAll && plan && (
        <ConfirmDialog
          title={`Restore ${plan.things.toLocaleString()} deleted ${plan.things === 1 ? 'thing' : 'things'}`}
          body={
            <div className="space-y-2">
              <p>
                {[
                  plan.collections &&
                    `${plan.collections.toLocaleString()} collection${plan.collections === 1 ? '' : 's'}`,
                  plan.schemas &&
                    `${plan.schemas.toLocaleString()} schema${plan.schemas === 1 ? '' : 's'}`,
                  plan.fields &&
                    `${plan.fields.toLocaleString()} field${plan.fields === 1 ? '' : 's'}`,
                  plan.records &&
                    `${plan.records.toLocaleString()} record${plan.records === 1 ? '' : 's'}`,
                ]
                  .filter(Boolean)
                  .join(', ')}{' '}
                come back, {plan.restores.toLocaleString()} record
                {plan.restores === 1 ? '' : 's'} in all with what was deleted
                alongside them.
              </p>
              {plan.blocked > 0 && (
                <p>
                  {plan.blocked.toLocaleString()} stay deleted: something they
                  belong to is deleted and is not in this list, or a field's
                  name has since been taken.
                </p>
              )}
              {plan.truncated && (
                <p>
                  More matched than could be counted here; restore again for the
                  rest.
                </p>
              )}
            </div>
          }
          confirmLabel="Restore all"
          isPending={restoreAll.isPending}
          onConfirm={() => restoreAll.mutate(query)}
          onClose={() => setConfirmAll(false)}
        />
      )}
      {open?.batch && (
        <BatchDialog
          event={open}
          title={describeAuditEvent(open).title}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  )
}
