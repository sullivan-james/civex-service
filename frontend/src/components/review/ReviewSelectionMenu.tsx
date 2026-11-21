import type { RecordSelection } from '../../api/records'
import type { ReviewStatus } from '../../api/review'
import { useSetReview } from '../../hooks/useReview'
import { usePermissions } from '../../hooks/useMe'
import { REVIEW_LABELS, REVIEW_STATUSES } from '../../utils/review'
import { Button, Menu, useToast } from '../ui'
import { ChevronDown } from '../ui/icons'

const plural = (n: number) =>
  `${n.toLocaleString()} record${n === 1 ? '' : 's'}`

/** The selection bar's **Review**: mark the records ticked (or all matching)
 * as needing a check, checked, or not reviewed, in one request. */
export function ReviewSelectionMenu({
  selection,
  count,
  collectionId,
  onDone,
}: {
  selection: RecordSelection
  count: number
  collectionId: string | null | undefined
  onDone: () => void
}) {
  const toast = useToast()
  const setReview = useSetReview()
  const { can, why } = usePermissions()
  const mayWrite = can('write_records', collectionId)

  function choose(status: ReviewStatus) {
    setReview.mutate(
      { selection, status },
      {
        onSuccess: (result) => {
          toast.success(
            status === 'none'
              ? `Cleared the review of ${plural(result.changed)}.`
              : `Marked ${plural(result.changed)} as ${REVIEW_LABELS[status].toLowerCase()}.` +
                  (result.unchanged
                    ? ` ${plural(result.unchanged)} already were.`
                    : ''),
          )
          onDone()
        },
        onError: (err) =>
          toast.error(
            `Couldn't mark them: ${err instanceof Error ? err.message : 'something went wrong'}`,
          ),
      },
    )
  }

  return (
    <Menu
      items={REVIEW_STATUSES.map((s) => ({
        label:
          s === 'none'
            ? 'Clear the review'
            : `Mark as ${REVIEW_LABELS[s].toLowerCase()}`,
        onClick: () => choose(s),
      }))}
      trigger={({ toggle, open }) => (
        <Button
          size="sm"
          aria-haspopup="menu"
          aria-expanded={open}
          disabled={!mayWrite || setReview.isPending || count === 0}
          title={mayWrite ? `Review ${plural(count)}` : why('write_records')}
          onClick={toggle}
        >
          {setReview.isPending ? 'Marking…' : 'Review'}
          <ChevronDown size={14} aria-hidden="true" />
        </Button>
      )}
    />
  )
}
