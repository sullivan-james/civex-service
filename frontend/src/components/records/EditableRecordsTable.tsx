import { useState } from 'react'
import { Link } from 'react-router'
import type { Schema } from '../../api/schemas'
import type { CivexRecord } from '../../api/records'
import { useCreateRecord, useUpdateRecord } from '../../hooks/useRecords'
import {
  Badge,
  Button,
  ConfirmDialog,
  DataTable,
  DataTableCell,
  IconButton,
  type DataTableColumn,
} from '../ui'
import { Plus, X } from '../ui/icons'
import { displayLabel } from '../../utils/naming'
import { formatDate } from '../../lib/utils'
import { buildRecordData, withFieldValue } from '../../utils/recordValues'
import { EditableCell } from './EditableCell'

function recordName(r: CivexRecord): string {
  return r.natural_name ?? `record ${r.id.slice(0, 8)}`
}

/** All records of one schema under a parent record, as a table where every
 * cell edits in place and a trailing draft row creates new records. Edits
 * save per cell; the draft row keeps its values locally until "Add". */
export function EditableRecordsTable({
  schema,
  records,
  collectionName,
  parentRecordId,
  onDelete,
}: {
  schema: Schema
  records: CivexRecord[]
  collectionName: string
  parentRecordId: string
  onDelete: (id: string) => void
}) {
  const cols = schema.fields
  const updateRecord = useUpdateRecord({ quiet: true })
  const createRecord = useCreateRecord(collectionName)
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const confirmRecord = records.find((r) => r.id === confirmId) ?? null
  const schemaLabel = displayLabel(schema.name, schema.label)

  function addRecord() {
    createRecord.mutate(
      {
        schema_name: schema.name,
        data: buildRecordData(cols, draft),
        parent_record_id: parentRecordId,
      },
      { onSuccess: () => setDraft({}) },
    )
  }

  const columns: DataTableColumn<CivexRecord>[] = [
    {
      key: '__name',
      header: 'Name',
      width: '9rem',
      render: (r) => (
        <Link to={`/records/${r.id}`} className="text-accent hover:underline">
          {r.natural_name ?? (
            <span className="font-mono">{r.id.slice(0, 8)}</span>
          )}
        </Link>
      ),
    },
    ...cols.map((col): DataTableColumn<CivexRecord> => ({
      key: col.name,
      header: displayLabel(col.name, col.label),
      headerTitle: col.name,
      rawCell: true,
      render: (r) => (
        <EditableCell
          key={col.name}
          field={col}
          value={r.data[col.name]}
          referenceLabels={r.reference_labels}
          referenceCollections={r.reference_collections}
          rowLabel={recordName(r)}
          onCommit={async (value) => {
            await updateRecord.mutateAsync({
              id: r.id,
              data: withFieldValue(r.data, col.name, value),
            })
          }}
        />
      ),
    })),
    {
      key: '__added',
      header: 'Added',
      width: '8rem',
      className: 'text-fg-muted',
      render: (r) => formatDate(r.created_at),
    },
    {
      key: '__delete',
      header: <span className="sr-only">Delete</span>,
      width: '3.5rem',
      render: (r) => (
        <IconButton
          icon={X}
          variant="danger"
          aria-label={`Delete ${recordName(r)}`}
          onClick={() => setConfirmId(r.id)}
        />
      ),
    },
  ]

  // Draft row: the same cells, committing to local state until Add.
  const draftRow = (
    <tr className="bg-canvas">
      <DataTableCell className="text-fg-muted italic">
        New {schemaLabel}
      </DataTableCell>
      {cols.map((col) => (
        <EditableCell
          key={col.name}
          field={col}
          value={draft[col.name]}
          rowLabel="new record"
          disabled={createRecord.isPending}
          onCommit={(value) => setDraft((d) => ({ ...d, [col.name]: value }))}
        />
      ))}
      <DataTableCell />
      <DataTableCell>
        <Button
          size="sm"
          variant="primary"
          onClick={addRecord}
          disabled={createRecord.isPending}
        >
          <Plus size={12} /> {createRecord.isPending ? 'Adding…' : 'Add'}
        </Button>
      </DataTableCell>
    </tr>
  )

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-fg flex items-center gap-2">
        <Link to={`/schemas/${schema.id}`}>
          <Badge variant="accent">{schemaLabel}</Badge>
        </Link>
        <span className="font-normal text-fg-muted">
          {records.length} record{records.length !== 1 ? 's' : ''}
        </span>
      </h3>
      <DataTable
        layout="auto"
        columns={columns}
        rows={records}
        getRowId={(r) => r.id}
        footer={draftRow}
      />
      {confirmRecord && (
        <ConfirmDialog
          title="Delete record"
          body={`Delete ${recordName(confirmRecord)}? It'll move to Recently Deleted — restore any time before it's permanently purged.`}
          confirmLabel="Delete record"
          variant="danger"
          onConfirm={() => {
            onDelete(confirmRecord.id)
            setConfirmId(null)
          }}
          onClose={() => setConfirmId(null)}
        />
      )}
    </div>
  )
}
