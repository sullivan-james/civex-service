import { keepPreviousData, useQuery } from '@tanstack/react-query'
import type { AuditLogEntry, PaginatedAuditLog } from '../../api/audit'
import type { TableQueryParams } from '../../api/query'
import { useTableState } from '../../hooks/useTableState'
import { TableControls } from '../table/TableControls'
import { tableFields } from '../../utils/tableFields'
import { nextSort } from '../../utils/tableState'
import type { AuditSummary } from '../../utils/schemaAudit'
import { DataTable, Badge, Pagination } from '../ui'
import { errorMessage } from '../../lib/errors'

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

const AUDIT_FIELDS = tableFields([
  { name: 'timestamp', label: 'When', type: 'datetime' },
  {
    name: 'action',
    label: 'Action',
    type: 'enum',
    choices: Object.keys(ACTION_VARIANT),
  },
])

/**
 * The audit trail for a single entity (record, schema or collection):
 * a "when / action / change" table, filterable and sortable like any list.
 * Mount it in a History tab.
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
    table: TableQueryParams,
  ) => Promise<PaginatedAuditLog>
  describeEntry: (entry: AuditLogEntry) => AuditSummary
  emptyMessage: string
  /** Prefix for this table's address parameters. */
  ns?: string
}) {
  const { state, patch } = useTableState(ns, 25)
  const table: TableQueryParams = { filter: state.filter, sort: state.sort }
  const { data, isLoading, error } = useQuery({
    queryKey: [...queryKey, state.page, state.pageSize, table],
    queryFn: () =>
      fetchPage(state.page * state.pageSize, state.pageSize, table),
    placeholderData: keepPreviousData,
  })

  return (
    <div className="space-y-3">
      <TableControls state={state} patch={patch} fields={AUDIT_FIELDS} />
      <DataTable
        sort={
          state.sort[0]
            ? { key: state.sort[0].field, direction: state.sort[0].direction }
            : undefined
        }
        onSortChange={(key) => patch({ sort: nextSort(state.sort, key) })}
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
        isLoading={isLoading}
        error={error ? errorMessage(error) : undefined}
        emptyTitle={state.filter ? 'No entries match' : 'No history yet'}
        emptyMessage={state.filter ? undefined : emptyMessage}
      />
      {data && data.items.length > 0 && (
        <Pagination
          page={state.page}
          pageSize={state.pageSize}
          total={data.total}
          onPage={(page) => patch({ page })}
          onPageSize={(pageSize) => patch({ pageSize })}
        />
      )}
    </div>
  )
}
