import { useState } from 'react'
import { useCollectionAudit } from '../../hooks/useCollections'
import { CollapsibleSection } from '../ui'
import { AuditHistoryTable } from '../audit/AuditHistoryTable'
import { describeAuditEntry } from '../../utils/collectionAudit'

export function CollectionHistory({
  collectionName,
}: {
  collectionName: string
}) {
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(25)
  const { data, isLoading, error } = useCollectionAudit(
    collectionName,
    page,
    pageSize,
  )

  return (
    <CollapsibleSection title="History" count={data?.total}>
      <AuditHistoryTable
        data={data}
        isLoading={isLoading}
        error={error}
        page={page}
        pageSize={pageSize}
        onPage={setPage}
        onPageSize={setPageSize}
        describeEntry={describeAuditEntry}
        emptyMessage="Changes to this collection will appear here."
      />
    </CollapsibleSection>
  )
}
