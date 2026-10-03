import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { AuditLogEntry, PaginatedAuditLog } from '../../api/audit'
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

/**
 * The audit trail for a single entity (record, schema or collection):
 * a "when / action / change" table. Mount it in a History tab.
 */
export function AuditTrail({
  queryKey,
  fetchPage,
  describeEntry,
  emptyMessage,
}: {
  /** Base react-query key for this entity's audit log; page/pageSize are appended. */
  queryKey: readonly unknown[]
  fetchPage: (offset: number, limit: number) => Promise<PaginatedAuditLog>
  describeEntry: (entry: AuditLogEntry) => AuditSummary
  emptyMessage: string
}) {
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(25)
  const { data, isLoading, error } = useQuery({
    queryKey: [...queryKey, page, pageSize],
    queryFn: () => fetchPage(page * pageSize, pageSize),
  })

  return (
    <>
      <DataTable
        layout="auto"
        columns={[
          {
            key: 'when',
            header: 'When',
            width: '12rem',
            className: 'text-fg-muted whitespace-nowrap',
            render: (e: AuditLogEntry) =>
              new Date(e.timestamp).toLocaleString(),
          },
          {
            key: 'action',
            header: 'Action',
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
        emptyTitle="No history yet"
        emptyMessage={emptyMessage}
      />
      {data && data.items.length > 0 && (
        <Pagination
          page={page}
          pageSize={pageSize}
          total={data.total}
          onPage={setPage}
          onPageSize={(size) => {
            setPageSize(size)
            setPage(0)
          }}
        />
      )}
    </>
  )
}
