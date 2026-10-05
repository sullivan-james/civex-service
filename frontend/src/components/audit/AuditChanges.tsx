import { Fragment } from 'react'
import type { AuditChange } from '../../api/audit'
import { changeLabel } from '../../utils/auditValues'
import { RestoreFieldButton } from '../trash/RestoreFieldButton'
import { AuditValue } from './AuditValue'

/** The first few changes on one line: "Age 1 → 2; Note (none) → hello". For a
 * table row; the whole list is `AuditChangeList`. */
export function AuditChangeSummary({
  changes,
  action,
  max = 3,
}: {
  changes: AuditChange[]
  action: string
  max?: number
}) {
  if (!changes.length) return null
  const shown = changes.slice(0, max)
  const more = changes.length - shown.length
  return (
    <>
      {shown.map((c, i) => (
        <Fragment key={c.field}>
          {i > 0 && '; '}
          {changeLabel(c)} <ChangeValues change={c} action={action} compact />
        </Fragment>
      ))}
      {more > 0 && ` … and ${more} more`}
    </>
  )
}

function ChangeValues({
  change,
  action,
  compact = false,
}: {
  change: AuditChange
  action: string
  compact?: boolean
}) {
  const show = (value: unknown) => (
    <AuditValue value={value} dtype={change.dtype} compact={compact} />
  )
  // A create has nothing before it and a delete nothing after, so say only
  // what is there instead of "(none) → x".
  if (action === 'create') return <>{show(change.after)}</>
  if (action === 'delete' || action === 'purge')
    return <>{show(change.before)}</>
  return (
    <>
      {show(change.before)} → {show(change.after)}
    </>
  )
}

/** Said beside a change to a field that has since been deleted: whether it can
 * still come back, and the button that does it. */
function DeletedFieldNote({ change }: { change: AuditChange }) {
  const gone = change.deleted
  if (!gone) return null
  if (gone.status === 'gone')
    return (
      <span className="block text-xs text-fg-subtle">
        Deleted field, gone for good
      </span>
    )
  return (
    <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-attention">
      Deleted field
      {gone.deleted_at &&
        ` · ${new Date(gone.deleted_at).toLocaleDateString()}`}
      {gone.schema_name && (
        <RestoreFieldButton fieldId={gone.id} schemaName={gone.schema_name} />
      )}
    </span>
  )
}

/** Every change an entry made, one per row, for the entry's detail. */
export function AuditChangeList({
  changes,
  action,
}: {
  changes: AuditChange[]
  action: string
}) {
  if (!changes.length)
    return <p className="text-sm text-fg-muted">No field values changed.</p>
  return (
    <dl className="divide-y divide-border">
      {changes.map((c) => (
        <div
          key={c.field}
          className="grid gap-1 py-2 sm:grid-cols-[10rem_1fr] sm:gap-4"
        >
          <dt className="text-xs font-medium text-fg-muted">
            {changeLabel(c)}
            <DeletedFieldNote change={c} />
          </dt>
          <dd className="min-w-0 text-sm text-fg break-words">
            <ChangeValues change={c} action={action} />
          </dd>
        </div>
      ))}
    </dl>
  )
}
