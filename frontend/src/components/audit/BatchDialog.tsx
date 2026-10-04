import { useState } from 'react'
import { Link } from 'react-router'
import type { AuditEvent, AuditLogEntry } from '../../api/audit'
import { useBatchEntries } from '../../hooks/useAudit'
import { errorMessage } from '../../lib/errors'
import { describeAnyAuditEntry, describeParts } from '../../utils/activityAudit'
import {
  Button,
  DataTable,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Pagination,
} from '../ui'
import { AuditEntryDialog } from './AuditEntryDialog'
import { EntrySubject } from './EntrySubject'

const PAGE = 25

/** What a batch did, and the changes in it a page at a time. Each opens as the
 * single change it is, with its own Revert for a record. */
export function BatchDialog({
  event,
  title,
  onClose,
}: {
  event: AuditEvent
  title: string
  onClose: () => void
}) {
  const batch = event.batch!
  const [page, setPage] = useState(0)
  const [member, setMember] = useState<AuditLogEntry | null>(null)
  const { data, isLoading, error } = useBatchEntries(batch.id, page, PAGE)

  return (
    <Modal onClose={onClose} size="xl">
      <ModalHeader onClose={onClose}>{title}</ModalHeader>
      <ModalBody className="space-y-3">
        <p className="text-sm text-fg-muted">
          {new Date(event.timestamp).toLocaleString()} ·{' '}
          {describeParts(event.parts)}
        </p>
        {batch.kind === 'workflow' && batch.ref && (
          <Link
            to={`/runs/${batch.ref}`}
            className="text-sm text-accent hover:underline"
          >
            Open the run
          </Link>
        )}
        <DataTable
          layout="auto"
          dense
          onRowClick={setMember}
          columns={[
            {
              key: 'change',
              header: 'Changes',
              render: (e: AuditLogEntry) => {
                const { title: t, detail } = describeAnyAuditEntry(e)
                return (
                  <div className="flex flex-col gap-0.5">
                    <span>{t}</span>
                    <EntrySubject entry={e} />
                    {detail && (
                      <span className="text-xs text-fg-muted">{detail}</span>
                    )}
                  </div>
                )
              },
            },
          ]}
          rows={data?.items ?? []}
          getRowId={(e) => e.id}
          isLoading={isLoading}
          error={error ? errorMessage(error) : undefined}
          emptyTitle="Nothing in this batch"
        />
        {data && data.total > PAGE && (
          <Pagination
            page={page}
            pageSize={PAGE}
            total={data.total}
            onPage={setPage}
            onPageSize={() => {}}
          />
        )}
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>Close</Button>
      </ModalFooter>
      {member && (
        <AuditEntryDialog
          entry={member}
          title={describeAnyAuditEntry(member).title}
          onClose={() => setMember(null)}
        />
      )}
    </Modal>
  )
}
