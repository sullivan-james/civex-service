import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { AuditLogEntry, PaginatedAuditLog } from '../../api/audit'
import type { AuditSummary } from '../../utils/schemaAudit'
import {
  CollapsibleSection,
  Table,
  Thead,
  Th,
  Tbody,
  Tr,
  Td,
  Badge,
  Pagination,
  TableSkeleton,
  ErrorState,
  EmptyState,
} from '../ui'
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
 * a "when / action / change" table, collapsed by default. It's a backup
 * feature for tracing what happened, not a primary surface, so it stays
 * out of the way until someone opens it.
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
    <CollapsibleSection title="History" count={data?.total}>
      {isLoading ? (
        <TableSkeleton columns={['w-40', 'w-20', 'w-full']} rows={5} />
      ) : error ? (
        <ErrorState message={errorMessage(error)} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState title="No history yet" message={emptyMessage} />
      ) : (
        <>
          <Table>
            <Thead>
              <tr>
                <Th className="w-44">When</Th>
                <Th className="w-24">Action</Th>
                <Th>Change</Th>
              </tr>
            </Thead>
            <Tbody>
              {data.items.map((entry) => {
                const { title, detail } = describeEntry(entry)
                return (
                  <Tr key={entry.id}>
                    <Td className="text-xs text-fg-muted whitespace-nowrap">
                      {new Date(entry.timestamp).toLocaleString()}
                    </Td>
                    <Td>
                      <Badge
                        variant={ACTION_VARIANT[entry.action] ?? 'default'}
                      >
                        {entry.action}
                      </Badge>
                    </Td>
                    <Td>
                      <div className="flex flex-col gap-0.5">
                        <span className="text-sm text-fg">{title}</span>
                        {detail && (
                          <span className="text-xs text-fg-muted">
                            {detail}
                          </span>
                        )}
                      </div>
                    </Td>
                  </Tr>
                )
              })}
            </Tbody>
          </Table>
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
        </>
      )}
    </CollapsibleSection>
  )
}
