import { Link } from 'react-router'
import { useRecordName } from '../../hooks/useRecordName'
import { recordHistoryHref } from '../../utils/auditFilter'
import { ErrorState } from '../ui'

/** What a record's page says when there is no such record to show: deleted
 * (and so restorable), or gone, with where to see what happened either way. */
export function RecordMissing({ id }: { id: string }) {
  const { data } = useRecordName(id)
  const message = data?.deleted
    ? 'This record is deleted. It can be restored from its history.'
    : data === null
      ? "This record doesn't exist. It may have been permanently deleted."
      : 'Record not found.'
  return (
    <div className="space-y-3">
      <ErrorState message={message} />
      <p className="text-sm">
        <Link
          to={recordHistoryHref(id)}
          className="text-accent hover:underline"
        >
          See what happened to it
        </Link>
      </p>
    </div>
  )
}
