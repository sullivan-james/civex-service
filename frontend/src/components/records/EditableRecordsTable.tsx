import { useState } from 'react'
import { Link } from 'react-router'
import type { Schema } from '../../api/schemas'
import type { CivexRecord } from '../../api/records'
import { useCreateRecord, useUpdateRecord } from '../../hooks/useRecords'
import {
  Badge,
  Button,
  ConfirmDialog,
  Table,
  Tbody,
  Td,
  Th,
  Thead,
  Tr,
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
      <Table>
        <Thead>
          <tr>
            <Th className="w-24">Name</Th>
            {cols.map((c) => (
              <Th key={c.name} title={c.name}>
                {displayLabel(c.name, c.label)}
              </Th>
            ))}
            <Th className="w-28">Added</Th>
            <Th className="w-20" />
          </tr>
        </Thead>
        <Tbody>
          {records.map((r) => (
            <Tr key={r.id}>
              <Td>
                <Link
                  to={`/records/${r.id}`}
                  className="text-sm text-accent hover:underline"
                >
                  {r.natural_name ?? (
                    <span className="font-mono">{r.id.slice(0, 8)}</span>
                  )}
                </Link>
              </Td>
              {cols.map((col) => (
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
              ))}
              <Td className="text-fg-muted">{formatDate(r.created_at)}</Td>
              <Td>
                <button
                  onClick={() => setConfirmId(r.id)}
                  className="text-xs text-fg-muted hover:text-danger transition-colors"
                  title="Delete record"
                  aria-label={`Delete ${recordName(r)}`}
                >
                  <X size={14} />
                </button>
              </Td>
            </Tr>
          ))}
          {/* Draft row: the same cells, committing to local state until Add. */}
          <Tr>
            <Td className="text-fg-muted italic">New {schemaLabel}</Td>
            {cols.map((col) => (
              <EditableCell
                key={col.name}
                field={col}
                value={draft[col.name]}
                rowLabel="new record"
                disabled={createRecord.isPending}
                onCommit={(value) =>
                  setDraft((d) => ({ ...d, [col.name]: value }))
                }
              />
            ))}
            <Td />
            <Td>
              <Button
                size="sm"
                variant="primary"
                onClick={addRecord}
                disabled={createRecord.isPending}
              >
                <Plus size={12} /> {createRecord.isPending ? 'Adding…' : 'Add'}
              </Button>
            </Td>
          </Tr>
        </Tbody>
      </Table>
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
