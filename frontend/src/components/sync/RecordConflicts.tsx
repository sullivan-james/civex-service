import { formatDate } from '../../lib/utils'
import { describeAttempt, type ConflictLayout } from '../../utils/syncConflicts'
import { Button } from '../ui'

/** On a record's Fields tab: that some of this record's changes were not applied,
 * why (for a refused change or an edit against a delete), and the way into the
 * merge view where they are settled. Nothing while there is nothing to review. */
export function RecordConflicts({
  layout,
  onResolve,
}: {
  layout: ConflictLayout
  onResolve: () => void
}) {
  if (layout.count === 0) return null
  const n = layout.count
  return (
    <section
      aria-label="Changes not applied"
      className="mb-4 space-y-2 rounded-lg border border-attention-muted bg-attention-subtle p-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-attention">
          {n === 1
            ? '1 of your changes to this record was not applied'
            : `${n} of your changes to this record were not applied`}
        </h2>
        <Button size="sm" variant="primary" onClick={onResolve}>
          Resolve side by side
        </Button>
      </div>
      {layout.recordLevel.map((c) => (
        <p key={c.id} className="text-sm">
          {describeAttempt(c, formatDate)}
        </p>
      ))}
      {layout.count > layout.recordLevel.length && (
        <p className="text-xs text-fg-muted">
          The fields that clashed are marked below. The other side’s value was
          kept; yours is saved until you choose.
        </p>
      )}
    </section>
  )
}
