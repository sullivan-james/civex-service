import { useState } from 'react'
import { Link } from 'react-router'
import type { AuditEvent, AuditLogEntry } from '../../api/audit'
import { useBatchEntries } from '../../hooks/useAudit'
import { useRestoreSelected } from '../../hooks/useRestore'
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
  InfoTip,
} from '../ui'
import { RestoreBatchDialog } from '../trash/RestoreBatchDialog'
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
  const [restoring, setRestoring] = useState(false)
  // Picked records, by entry id -> the record's id; kept across pages so a
  // choice made on page one survives looking at page two.
  const [picked, setPicked] = useState<Map<string, string>>(new Map())
  const restoreSelected = useRestoreSelected(() => setPicked(new Map()))
  const { data, isLoading, error } = useBatchEntries(batch.id, page, PAGE)
  const rows = data?.items ?? []
  // Only a bulk delete is worth picking from: take back some of what it took.
  const canPick = batch.kind === 'delete'
  const setMany = (entries: AuditLogEntry[], on: boolean) =>
    setPicked((prev) => {
      const next = new Map(prev)
      for (const e of entries) {
        if (on) next.set(e.id, e.entity_id)
        else next.delete(e.id)
      }
      return next
    })

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
        {canPick && (
          <p className="flex items-center gap-1 text-sm text-fg-muted">
            Tick the records to bring back.
            <InfoTip>
              A record under a deleted record brings that one back too, by
              itself; the rest stays deleted.
            </InfoTip>
          </p>
        )}
        <DataTable
          layout="auto"
          dense
          onRowClick={setMember}
          selection={
            canPick
              ? {
                  selected: new Set(picked.keys()),
                  onToggle: (id) => {
                    const entry = rows.find((e) => e.id === id)
                    if (entry) setMany([entry], !picked.has(id))
                  },
                  onSetMany: (ids, on) =>
                    setMany(
                      rows.filter((e) => ids.includes(e.id)),
                      on,
                    ),
                  onToggleAll: () =>
                    setMany(
                      rows,
                      !(rows.length > 0 && rows.every((e) => picked.has(e.id))),
                    ),
                  allLabel: 'Select every record on this page',
                  rowLabel: () => 'Select this record',
                }
              : undefined
          }
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
          rows={rows}
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
        {batch.kind === 'delete' && picked.size > 0 && (
          <Button
            variant="primary"
            disabled={restoreSelected.isPending}
            onClick={() => restoreSelected.mutate([...picked.values()])}
          >
            {restoreSelected.isPending
              ? 'Restoring…'
              : `Restore ${picked.size.toLocaleString()} selected`}
          </Button>
        )}
        {batch.kind === 'delete' && (
          <Button
            variant={picked.size > 0 ? 'default' : 'primary'}
            onClick={() => setRestoring(true)}
          >
            Restore everything…
          </Button>
        )}
      </ModalFooter>
      {restoring && (
        <RestoreBatchDialog
          batchId={batch.id}
          onClose={() => setRestoring(false)}
        />
      )}
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
