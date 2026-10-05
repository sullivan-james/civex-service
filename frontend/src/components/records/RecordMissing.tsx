import { useState } from 'react'
import { Link } from 'react-router'
import { useRecordName } from '../../hooks/useRecordName'
import { useRestorePlan } from '../../hooks/useRestore'
import { recordHistoryHref } from '../../utils/auditFilter'
import { RestoreDialog } from '../trash/RestoreDialog'
import { Button, ErrorState } from '../ui'

/** What a record's page says when there is no such record to show: deleted
 * (and so restorable), or gone, with where to see what happened either way. A
 * deleted record says when, and if it went with its schema, that too, with the
 * button that brings it back (the dialog offers the schema first). */
export function RecordMissing({ id }: { id: string }) {
  const { data } = useRecordName(id)
  const deleted = !!data?.deleted
  const { data: plan } = useRestorePlan({ kind: 'record', ref: id }, deleted)
  const [restoring, setRestoring] = useState(false)
  const when = data?.deleted_at
    ? ` on ${new Date(data.deleted_at).toLocaleDateString()}`
    : ''
  const message = deleted
    ? `This record was deleted${when}. It can be restored.`
    : data === null
      ? "This record doesn't exist. It may have been permanently deleted."
      : 'Record not found.'
  const blocker = plan?.blocked_by
  return (
    <div className="space-y-3">
      <ErrorState message={message} />
      {blocker && (
        <p className="text-sm text-fg-muted">
          It is{' '}
          {blocker.kind === 'schema'
            ? 'typed by the schema'
            : blocker.kind === 'collection'
              ? 'in the collection'
              : 'under the record'}{' '}
          “{blocker.name}”, which is deleted too. Restoring it brings both back.
        </p>
      )}
      <p className="flex flex-wrap items-center gap-3 text-sm">
        {deleted && (
          <Button variant="primary" onClick={() => setRestoring(true)}>
            Restore…
          </Button>
        )}
        <Link
          to={recordHistoryHref(id)}
          className="text-accent hover:underline"
        >
          See what happened to it
        </Link>
      </p>
      {restoring && (
        <RestoreDialog
          target={{ kind: 'record', ref: id }}
          onClose={() => setRestoring(false)}
        />
      )}
    </div>
  )
}
