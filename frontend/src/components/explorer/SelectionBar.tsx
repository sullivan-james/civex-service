import { Button } from '../ui'

/** Shown while rows are ticked. Ticking a whole page offers "select all N
 * matching", so a bulk action can cover every record the filters match, not
 * only the ones on screen -- and says so, with the real count. */
export function SelectionBar({
  selectedCount,
  pageCount,
  total,
  allMatching,
  onSelectAllMatching,
  onClear,
  onDelete,
  deleting,
}: {
  selectedCount: number
  pageCount: number
  total: number
  allMatching: boolean
  onSelectAllMatching: () => void
  onClear: () => void
  onDelete: () => void
  deleting: boolean
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
      <Button variant="danger" size="sm" disabled={deleting} onClick={onDelete}>
        {deleting ? 'Deleting…' : `Delete ${count.toLocaleString()}`}
      </Button>
      <Button size="sm" variant="ghost" onClick={onClear}>
        Clear selection
      </Button>
    </div>
  )
}
