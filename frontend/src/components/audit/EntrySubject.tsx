import { Link } from 'react-router'
import type { AuditLogEntry } from '../../api/audit'
import { auditEntryTarget } from '../../utils/activityAudit'
import { MonoId } from '../ui'

/** What an entry is about: its name, which opens it when it can be opened, its
 * id, and the collection it is in. A record that is deleted or gone for good has
 * no page to open, so it is shown plainly, with its id to find it by. `full`
 * writes the whole id, selectable, for the entry's own detail. */
export function EntrySubject({
  entry,
  full = false,
}: {
  entry: AuditLogEntry
  full?: boolean
}) {
  const now = entry.now
  const snapshot = entry.new_data ?? entry.old_data
  const isRecord = entry.entity_type === 'record'
  const name = isRecord
    ? (now?.name ?? now?.schema_name ?? 'Record')
    : ((snapshot?.name as string | undefined) ?? entry.entity_type)
  const target = auditEntryTarget(entry)
  // Something deleted (or gone for good) has no page to open: a link would only
  // lead to "not found". Its row says where it is now instead.
  const openable = target && !(now && now.status !== 'live')

  return (
    <span className="flex flex-wrap items-center gap-x-2 text-sm">
      {openable ? (
        <Link
          to={target.to}
          className="font-medium text-accent hover:underline"
          title={`Open ${target.label.toLowerCase()}`}
        >
          {name}
        </Link>
      ) : (
        <span className="font-medium text-fg">{name}</span>
      )}
      {full ? (
        <code className="select-all font-mono text-xs text-fg-muted">
          {entry.entity_id}
        </code>
      ) : (
        <MonoId id={entry.entity_id} />
      )}
      {isRecord && now?.collection && (
        <span className="text-xs text-fg-subtle">in {now.collection}</span>
      )}
    </span>
  )
}
