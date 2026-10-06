import { Link } from 'react-router'
import type { SyncConflict } from '../../api/remote'
import { Badge } from '../ui'

/** The record a conflict is about, as a person knows it: its name, where it is,
 * and a link to settle it, instead of an id. */
export function ConflictSubject({ conflict: c }: { conflict: SyncConflict }) {
  const name = c.record_name ?? `${c.entity_type} ${c.entity_id.slice(0, 8)}`
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      {c.entity_type === 'record' && !c.record_deleted ? (
        <Link
          to={`/records/${c.entity_id}?tab=resolve`}
          className="font-medium"
        >
          {name}
        </Link>
      ) : (
        <span className="font-medium">{name}</span>
      )}
      {c.schema_name && <Badge variant="accent">{c.schema_name}</Badge>}
      {c.dataset_name && (
        <span className="text-xs text-fg-muted">in {c.dataset_name}</span>
      )}
      {c.record_deleted && <Badge variant="attention">deleted</Badge>}
    </span>
  )
}
