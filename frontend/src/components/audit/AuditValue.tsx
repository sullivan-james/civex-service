import { Fragment, type ReactNode } from 'react'
import { isBlank, isFileRef, valueText } from '../../utils/auditValues'
import { FetchedReferenceLink } from '../records/ReferenceLink'

const COMPACT_LIMIT = 60

/** One value in a history entry. A reference links to the record it points at,
 * a file shows its name, and structured values (a field's restrictions, a
 * view's filter) are laid out in full, or on one line when `compact`. */
export function AuditValue({
  value,
  dtype,
  compact = false,
}: {
  value: unknown
  dtype?: string | null
  compact?: boolean
}): ReactNode {
  if (isBlank(value)) return <span className="text-fg-muted">(none)</span>
  if (dtype === 'reference' && typeof value === 'string')
    return <FetchedReferenceLink id={value} />
  if (dtype === 'reference_list' && Array.isArray(value))
    return value.map((v, i) => (
      <Fragment key={String(v)}>
        {i > 0 && ', '}
        <FetchedReferenceLink id={String(v)} />
      </Fragment>
    ))
  if (isFileRef(value) || typeof value !== 'object') return valueText(value)
  if (Array.isArray(value) && value.every((v) => typeof v !== 'object'))
    return valueText(value)
  if (Array.isArray(value) && value.every(isFileRef)) return valueText(value)
  if (compact) {
    const text = valueText(value)
    return text.length > COMPACT_LIMIT
      ? `${text.slice(0, COMPACT_LIMIT - 1)}…`
      : text
  }
  return (
    <code className="block whitespace-pre-wrap break-words font-mono text-xs">
      {JSON.stringify(value, null, 2)}
    </code>
  )
}
