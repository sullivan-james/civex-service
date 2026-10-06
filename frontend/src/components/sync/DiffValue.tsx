import { isBlank } from '../../utils/auditValues'
import { diffItems, diffText } from '../../utils/textDiff'
import { AuditValue } from '../audit/AuditValue'

/** Which side of the merge a value is on, for the colour of what differs. */
export type Side = 'left' | 'right'

const MARK: Record<Side, string> = {
  left: 'rounded-sm bg-accent-muted px-0.5',
  right: 'rounded-sm bg-success-muted px-0.5',
}

const isPlain = (v: unknown) =>
  v === null || ['string', 'number', 'boolean'].includes(typeof v)

/** One side's value, with the parts the other side lacks marked: the words that
 * differ in a text, the items missing from a list, the whole value otherwise. */
export function DiffValue({
  value,
  other,
  dtype,
  side,
}: {
  value: unknown
  other: unknown
  dtype: string | null
  side: Side
}) {
  if (isBlank(value))
    return (
      <span className="text-fg-muted">
        <AuditValue value={value} dtype={dtype} />
      </span>
    )

  if (
    typeof value === 'string' &&
    typeof other === 'string' &&
    value !== other
  ) {
    const d = diffText(
      side === 'left' ? value : other,
      side === 'left' ? other : value,
    )
    if (d) {
      return (
        <span className="whitespace-pre-wrap break-words">
          {d[side].map((s, i) =>
            s.changed ? (
              <mark key={i} className={`${MARK[side]} text-fg`}>
                {s.text}
              </mark>
            ) : (
              <span key={i}>{s.text}</span>
            ),
          )}
        </span>
      )
    }
  }

  if (
    Array.isArray(value) &&
    Array.isArray(other) &&
    value.every(isPlain) &&
    other.every(isPlain)
  ) {
    const d = diffItems(
      side === 'left' ? value : other,
      side === 'left' ? other : value,
    )[side]
    return (
      <span className="flex flex-wrap gap-1">
        {d.map(({ item, changed }, i) => (
          <span
            key={i}
            className={`rounded-sm border border-border px-1.5 text-sm ${
              changed ? `${MARK[side]} font-medium` : 'text-fg-muted'
            }`}
          >
            {String(item)}
          </span>
        ))}
      </span>
    )
  }

  // Anything else (a number, a date, a place, a reference): differing is the
  // whole of it, and the cell's own tint says so.
  return (
    <span className="whitespace-pre-wrap break-words">
      <AuditValue value={value} dtype={dtype} />
    </span>
  )
}
