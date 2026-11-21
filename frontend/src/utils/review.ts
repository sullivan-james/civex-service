import type { ReviewStatus, ReviewValue } from '../api/review'
import type { FilterableField } from './hierarchy'

/** The filter tree's names for a record's review status and its open notes,
 * and the explorer's column for the status (a field's name can't start with
 * `@`, so they never shadow one). Mirrors `civex.domain.review`. */
export const REVIEW_FILTER = '@review'
export const OPEN_NOTES_FILTER = '@open_notes'
/** What the filter chips call the record itself, in place of a schema. */
const RECORD = 'record'

export const REVIEW_STATUSES: ReviewStatus[] = [
  'none',
  'needs_check',
  'checked',
]

export const REVIEW_LABELS: Record<ReviewStatus, string> = {
  none: 'Not reviewed',
  needs_check: 'Needs a check',
  checked: 'Checked',
}

export function reviewStatus(
  review: ReviewValue | null | undefined,
): ReviewStatus {
  return review?.status ?? 'none'
}

/** The badge colour of a status. */
export function reviewTone(
  status: ReviewStatus,
): 'default' | 'attention' | 'success' {
  return status === 'needs_check'
    ? 'attention'
    : status === 'checked'
      ? 'success'
      : 'default'
}

/** The review status and open notes as fields of the filter builder, so the
 * explorer filters by them with its own controls. */
export function reviewFilterFields(): FilterableField[] {
  const base = {
    required: false,
    default: null,
    position: null,
    sourceSchemaName: RECORD,
    relation: 'self' as const,
    ownerless: true,
  }
  return [
    {
      ...base,
      id: 'record-review',
      name: REVIEW_FILTER,
      label: 'Review',
      type: 'enum',
      restrictions: { choices: REVIEW_STATUSES },
      operators: ['eq', 'ne', 'in'],
    },
    {
      ...base,
      id: 'record-open-notes',
      name: OPEN_NOTES_FILTER,
      label: 'Has open notes',
      type: 'boolean',
      restrictions: {},
      operators: ['eq'],
    },
  ] as FilterableField[]
}
