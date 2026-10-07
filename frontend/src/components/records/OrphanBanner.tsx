import type { CivexRecord } from '../../api/records'
import { useRestoreAbove } from '../../hooks/useRestore'
import { Button } from '../ui'
import { AlertTriangle } from '../ui/icons'

const name = (r: { natural_name: string | null; schema_name: string }) =>
  r.natural_name ? `${r.schema_name} ${r.natural_name}` : r.schema_name

/** Shown on a live record that sits under a deleted one: it is out of sight
 * (nothing above it lists it) and a sync server won't take it. The two ways
 * out: bring back what it sits under (each by itself, so their other children
 * stay deleted), or delete this record. */
export function OrphanBanner({
  record,
  onDelete,
}: {
  record: CivexRecord
  onDelete: () => void
}) {
  const restore = useRestoreAbove()
  const above = record.deleted_above ?? []
  if (above.length === 0) return null
  const parent = above[above.length - 1]
  const what = above.map(name).join(' › ')
  return (
    <div
      role="alert"
      className="mb-4 flex flex-wrap items-start gap-3 rounded-lg border border-attention-muted bg-attention-subtle p-3 text-sm"
    >
      <AlertTriangle
        size={16}
        className="mt-0.5 shrink-0 text-attention"
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="font-medium text-fg">
          This {record.schema_name} sits under {name(parent)}, which is deleted.
        </p>
        <p className="text-fg-muted">
          Nothing above it lists it, and a sync server won&apos;t take it until
          what it sits under is back.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="primary"
          disabled={restore.isPending}
          onClick={() => restore.mutate(record.id)}
        >
          Restore {what}
        </Button>
        <Button size="sm" variant="danger" onClick={onDelete}>
          Delete this {record.schema_name}
        </Button>
      </div>
    </div>
  )
}
