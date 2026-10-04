import { Link } from 'react-router'
import { useRecordName } from '../../hooks/useRecordName'
import { recordHistoryHref } from '../../utils/auditFilter'

/** A link to a record, from its id alone: wherever only the id was kept (a
 * run's record, the records it touched, a value in history).
 *
 * A record that can be opened is a link. One that is deleted, or permanently
 * deleted, has no page, so it is shown plainly and says so, with a way to see
 * what happened to it instead of a link that leads nowhere. `fallback` is the
 * name to show if the record can't supply one (older data that kept it). */
export function RecordLink({
  id,
  fallback,
  className = 'text-accent hover:underline',
}: {
  id: string
  fallback?: string | null
  className?: string
}) {
  const { data } = useRecordName(id) // undefined while loading, null if gone
  const name = data?.natural_name ?? fallback ?? `${id.slice(0, 8)}…`
  const state =
    data === null ? 'permanently deleted' : data?.deleted ? 'deleted' : null
  if (!state)
    return (
      <Link to={`/records/${id}`} className={className} title={id}>
        {name}
      </Link>
    )
  return (
    <span title={id}>
      <span className="text-fg-muted">{name}</span>{' '}
      <Link
        to={recordHistoryHref(id)}
        className="text-xs text-accent hover:underline"
      >
        ({state}: see history)
      </Link>
    </span>
  )
}
