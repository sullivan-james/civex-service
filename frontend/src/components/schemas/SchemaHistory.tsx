import { useState } from 'react'
import { useSchemaAudit } from '../../hooks/useSchemas'
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
import { describeAuditEntry } from '../../utils/schemaAudit'

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

export function SchemaHistory({ schemaName }: { schemaName: string }) {
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(25)
  const { data, isLoading, error } = useSchemaAudit(schemaName, page, pageSize)

  return (
    <div>
      <h2 className="text-base font-semibold text-fg mb-2">History</h2>
      {isLoading ? (
        <TableSkeleton columns={['w-40', 'w-20', 'w-full']} rows={5} />
      ) : error ? (
        <ErrorState message={errorMessage(error)} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          title="No history yet"
          message="Changes to this schema and its fields will appear here."
        />
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
                const { title, detail } = describeAuditEntry(entry)
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
    </div>
  )
}
