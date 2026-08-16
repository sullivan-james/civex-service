import type { AuditLogEntry, PaginatedAuditLog } from '../../api/audit'
import type { AuditSummary } from '../../utils/schemaAudit'
import {
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

/** The shared "when / action / change" audit table used by both schema and
 * collection history — entity-specific fetching and change-description logic
 * stay in the caller (see SchemaHistory / CollectionHistory). */
export function AuditHistoryTable({
  data,
  isLoading,
  error,
  page,
  pageSize,
  onPage,
  onPageSize,
  describeEntry,
  emptyTitle = 'No history yet',
  emptyMessage,
}: {
  data: PaginatedAuditLog | undefined
  isLoading: boolean
  error: unknown
  page: number
  pageSize: number
  onPage: (page: number) => void
  onPageSize: (pageSize: number) => void
  describeEntry: (entry: AuditLogEntry) => AuditSummary
  emptyTitle?: string
  emptyMessage: string
}) {
  if (isLoading)
    return <TableSkeleton columns={['w-40', 'w-20', 'w-full']} rows={5} />
  if (error) return <ErrorState message={errorMessage(error)} />
  if (!data || data.items.length === 0)
    return <EmptyState title={emptyTitle} message={emptyMessage} />

  return (
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
                  <Badge variant={ACTION_VARIANT[entry.action] ?? 'default'}>
                    {entry.action}
                  </Badge>
                </Td>
                <Td>
                  <div className="flex flex-col gap-0.5">
                    <span className="text-sm text-fg">{title}</span>
                    {detail && (
                      <span className="text-xs text-fg-muted">{detail}</span>
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
        onPage={onPage}
        onPageSize={(size) => {
          onPageSize(size)
          onPage(0)
        }}
      />
    </>
  )
}
