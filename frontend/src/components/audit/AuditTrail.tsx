import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import type {
  AuditLogEntry,
  AuditView,
  PaginatedAuditLog,
} from '../../api/audit'
import { useListParams } from '../../hooks/useListParams'
import type { AuditSummary } from '../../utils/schemaAudit'
import { DataTable, Badge, ListToolbar, Pagination } from '../ui'
import { errorMessage } from '../../lib/errors'
import { AuditEntryDialog } from './AuditEntryDialog'

const ACTION_VARIANT: Record<
  string,
  'default' | 'accent' | 'success' | 'danger'
> = {
  create: 'success',
  update: 'accent',
  delete: 'danger',
  restore: 'accent',
  purge: 'danger',
}

/**
 * The audit trail for a single entity (record, schema or collection):
 * a "when / action / change" table. Mount it in a History tab. A row opens
 * the entry in full, and for a change to a record offers to undo it.
 */
export function AuditTrail({
  queryKey,
  fetchPage,
  describeEntry,
  emptyMessage,
  ns = 'history.',
}: {
  /** Base react-query key for this entity's audit log; page/pageSize are appended. */
  queryKey: readonly unknown[]
  fetchPage: (
    offset: number,
    limit: number,
    view: AuditView,
  ) => Promise<PaginatedAuditLog>
  describeEntry: (entry: AuditLogEntry) => AuditSummary
  emptyMessage: string
  /** Prefix for this table's address parameters. */
  ns?: string
}) {
  const list = useListParams(ns, ['action'])
  const [open, setOpen] = useState<AuditLogEntry | null>(null)
  const view: AuditView = {
    action: list.picks.action || undefined,
    sort: list.sortParam,
  }
  const { data, isLoading, error } = useQuery({
    queryKey: [...queryKey, list.page, list.size, view],
    queryFn: () => fetchPage(list.page * list.size, list.size, view),
    placeholderData: keepPreviousData,
  })

  return (
    <div className="space-y-3">
      <ListToolbar
        picks={[
          {
            label: 'Any action',
            value: list.picks.action,
            options: [
              { value: '', label: 'Any action' },
              ...Object.keys(ACTION_VARIANT).map((a) => ({
                value: a,
                label: a,
              })),
            ],
            onChange: (action) => list.set({ action }),
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
        layout="auto"
        columns={[
          {
            key: 'timestamp',
            header: 'When',
            sortable: true,
            width: '12rem',
            className: 'text-fg-muted whitespace-nowrap',
            render: (e: AuditLogEntry) =>
              new Date(e.timestamp).toLocaleString(),
          },
          {
            key: 'action',
            header: 'Action',
            sortable: true,
            width: '7rem',
            render: (e) => (
              <Badge variant={ACTION_VARIANT[e.action] ?? 'default'}>
                {e.action}
              </Badge>
            ),
          },

          {
            key: 'change',
            header: 'Change',
            render: (e) => {
              const { title, detail } = describeEntry(e)
              return (
                <div className="flex flex-col gap-0.5">
                  <span>{title}</span>
                  {detail && (
                    <span className="text-xs text-fg-muted">{detail}</span>
                  )}
                </div>
              )
            },
          },
        ]}
        rows={data?.items ?? []}
        getRowId={(e) => String(e.id)}
        onRowClick={setOpen}
        isLoading={isLoading}
        error={error ? errorMessage(error) : undefined}
        emptyTitle={list.picks.action ? 'No entries match' : 'No history yet'}
        emptyMessage={list.picks.action ? undefined : emptyMessage}
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
      {open && (
        <AuditEntryDialog
          entry={open}
          title={describeEntry(open).title}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  )
}
