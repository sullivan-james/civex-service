import type { ReviewStatus, ReviewValue } from '../../api/review'
import { useSetReview } from '../../hooks/useReview'
import { usePermissions } from '../../hooks/useMe'
import { formatDateTime } from '../../utils/dates'
import {
  REVIEW_LABELS,
  REVIEW_STATUSES,
  reviewStatus,
  reviewTone,
} from '../../utils/review'
import { Badge, Button, Menu, useToast } from '../ui'
import { ChevronDown } from '../ui/icons'

/** A record's review status in its page header: the status as a badge (who set
 * it and when on hover), and a menu to change it. Switched off, with the
 * reason, for someone who may not write records in its collection. */
export function ReviewStatusMenu({
  recordId,
  collectionId,
  review,
}: {
  recordId: string
  collectionId: string
  review: ReviewValue | null | undefined
}) {
  const toast = useToast()
  const setReview = useSetReview()
  const { can, why } = usePermissions()
  const status = reviewStatus(review)
  const mayWrite = can('write_records', collectionId)
  const said = review
    ? `${REVIEW_LABELS[status]}: ${review.by ?? 'someone'}, ${formatDateTime(review.at)}`
    : REVIEW_LABELS.none

  function choose(next: ReviewStatus) {
    setReview.mutate(
      { selection: { ids: [recordId] }, status: next },
      {
        onError: (err) =>
          toast.error(
            `Couldn't mark it: ${err instanceof Error ? err.message : 'something went wrong'}`,
          ),
      },
    )
  }

  return (
    <Menu
      items={REVIEW_STATUSES.filter((s) => s !== status).map((s) => ({
        label:
          s === 'none'
            ? 'Clear the review'
            : `Mark as ${REVIEW_LABELS[s].toLowerCase()}`,
        onClick: () => choose(s),
      }))}
      trigger={({ toggle, open }) => (
        <Button
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label={`Review: ${REVIEW_LABELS[status]}`}
          title={mayWrite ? said : why('write_records')}
          disabled={!mayWrite || setReview.isPending}
          onClick={toggle}
        >
          <Badge variant={reviewTone(status)}>{REVIEW_LABELS[status]}</Badge>
          <ChevronDown size={14} aria-hidden="true" />
        </Button>
      )}
    />
  )
}

/** A review status as a small badge, for a table cell. */
export function ReviewBadge({
  review,
}: {
  review: ReviewValue | null | undefined
}) {
  const status = reviewStatus(review)
  if (status === 'none') return <span className="text-fg-subtle">—</span>
  return (
    <span
      title={
        review
          ? `${review.by ?? 'someone'}, ${formatDateTime(review.at)}`
          : undefined
      }
    >
      <Badge variant={reviewTone(status)}>{REVIEW_LABELS[status]}</Badge>
    </span>
  )
}
