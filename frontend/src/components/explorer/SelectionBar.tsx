import type { ReactNode } from 'react'
import { Button } from '../ui'

/** Shown while rows are ticked (`useBulkSelection`). Ticking a whole page
 * offers "select all N matching", so a bulk action can cover every row the
 * filters match, not only the ones on screen -- and says so, with the real
 * count. The page's own box clears it. Used by every paged list with bulk
 * actions (records, files). */
export function SelectionBar({
  selectedCount,
  pageCount,
  total,
  allMatching,
  onSelectAllMatching,
  onDelete,
  deleting = false,
  actions,
}: {
  selectedCount: number
  pageCount: number
  total: number
  allMatching: boolean
  onSelectAllMatching: () => void
  /** For a list whose rows can be deleted. */
  onDelete?: () => void
  deleting?: boolean
  /** Other things to do with the selection, before Delete. */
  actions?: ReactNode
}) {
  if (selectedCount === 0 && !allMatching) return null
  const count = allMatching ? total : selectedCount
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-accent-muted bg-accent-subtle px-3 py-2 text-sm">
      <span className="font-medium text-accent">
        {allMatching
          ? `All ${total.toLocaleString()} matching selected`
          : `${selectedCount.toLocaleString()} selected`}
      </span>
      {!allMatching && selectedCount === pageCount && total > pageCount && (
        <Button size="sm" variant="link" onClick={onSelectAllMatching}>
          Select all {total.toLocaleString()} matching
        </Button>
      )}
      {actions}
      {onDelete && (
        <Button
          variant="danger"
          size="sm"
          disabled={deleting}
          onClick={onDelete}
        >
          {deleting ? 'Deleting…' : `Delete ${count.toLocaleString()}`}
        </Button>
      )}
    </div>
  )
}
