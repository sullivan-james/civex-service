import { useRecordAudit } from '../../hooks/useRecords'
import { Badge } from '../ui'
import { formatDate } from '../../lib/utils'
import { displayLabel } from '../../utils/naming'
import { FieldValue } from './FieldValue'
import type { AuditLogEntry } from '../../api/records'

const ACTION_LABEL: Record<string, string> = {
  create: 'created',
  update: 'updated',
  delete: 'deleted',
  restore: 'restored',
  purge: 'permanently removed',
}

const ACTION_VARIANT: Record<
  string,
  'default' | 'accent' | 'success' | 'danger'
> = {
  create: 'success',
  update: 'accent',
  delete: 'danger',
  restore: 'success',
  purge: 'danger',
}

interface FieldChange {
  field: string
  before: unknown
  after: unknown
}

// old_data/new_data are full record snapshots ({id, data, created_at, ...})
// -- only the `data` sub-object holds field values, and only for
// create/update/restore is it name-keyed (delete/purge log the raw,
// id-keyed record data), so those two are shown without a field diff.
function diffData(entry: AuditLogEntry): FieldChange[] {
  if (entry.action === 'delete' || entry.action === 'purge') return []
  const before =
    (entry.old_data?.data as Record<string, unknown> | undefined) ?? null
  const after =
    (entry.new_data?.data as Record<string, unknown> | undefined) ?? null
  const fields = new Set([
    ...Object.keys(before ?? {}),
    ...Object.keys(after ?? {}),
  ])
  const changes: FieldChange[] = []
  for (const field of fields) {
    const b = before?.[field] ?? null
    const a = after?.[field] ?? null
    if (JSON.stringify(b) !== JSON.stringify(a)) {
      changes.push({ field, before: b, after: a })
    }
  }
  return changes.sort((x, y) => x.field.localeCompare(y.field))
}

function HistoryEntry({ entry }: { entry: AuditLogEntry }) {
  const changes = diffData(entry)
  return (
    <li className="text-sm">
      <div className="flex items-center gap-2">
        <Badge variant={ACTION_VARIANT[entry.action] ?? 'default'}>
          {ACTION_LABEL[entry.action] ?? entry.action}
        </Badge>
        <span className="text-fg-muted text-xs">
          {formatDate(entry.timestamp)}
        </span>
      </div>
      {changes.length > 0 && (
        <ul className="mt-1.5 space-y-1 border-l-2 border-border pl-3">
          {changes.map(({ field, before, after }) => (
            <li
              key={field}
              className="flex flex-wrap items-center gap-1.5 text-xs text-fg-muted"
            >
              <span className="font-medium text-fg">{displayLabel(field)}</span>
              {entry.action === 'create' ? (
                <FieldValue value={after} />
              ) : (
                <>
                  <FieldValue value={before} />
                  <span>→</span>
                  <FieldValue value={after} />
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

export default function RecordHistory({ recordId }: { recordId: string }) {
  const { data } = useRecordAudit(recordId)
  const entries = data?.items ?? []
  if (entries.length === 0) return null

  return (
    <div>
      <h2 className="text-base font-semibold text-fg mb-2">History</h2>
      <ul className="space-y-3">
        {entries.map((entry) => (
          <HistoryEntry key={entry.id} entry={entry} />
        ))}
      </ul>
    </div>
  )
}
