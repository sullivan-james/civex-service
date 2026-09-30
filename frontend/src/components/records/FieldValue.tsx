import { Badge } from '../ui'
import { ReferenceLink } from './ReferenceLink'
import { useFieldTimeZone } from './timeZoneContext'
import { formatDateTime } from '../../utils/dates'
import type { Field } from '../../api/schemas'

export function FieldValue({
  value,
  field,
  referenceLabels,
}: {
  value: unknown
  /** Reference/reference_list values render as links; every other type
   * falls back to the existing shape-based rendering below. */
  field?: Field
  referenceLabels?: Record<string, string | null> | null
}) {
  const timeZone = useFieldTimeZone(field)
  if (value === null || value === undefined)
    return <span className="text-fg-subtle">—</span>
  if (field?.type === 'datetime' && typeof value === 'string' && value)
    // Shown as wall time in the field's zone; the stored UTC value is on hover.
    return <span title={value}>{formatDateTime(value, timeZone)}</span>
  if (field?.type === 'reference' && typeof value === 'string')
    return <ReferenceLink id={value} labels={referenceLabels} />
  if (field?.type === 'reference_list' && Array.isArray(value)) {
    if (value.length === 0) return <span className="text-fg-subtle">—</span>
    return (
      <span className="flex flex-wrap gap-x-2 gap-y-1">
        {(value as string[]).map((id) => (
          <ReferenceLink key={id} id={id} labels={referenceLabels} />
        ))}
      </span>
    )
  }
  if (typeof value === 'boolean')
    return (
      <Badge variant={value ? 'success' : 'default'}>{String(value)}</Badge>
    )
  if (
    Array.isArray(value) &&
    value.length > 0 &&
    typeof value[0] === 'object' &&
    'sha256' in value[0]
  ) {
    const refs = value as { filename: string; size: number; sha256: string }[]
    return (
      <span className="flex flex-col gap-1">
        {refs.map((ref) => (
          <span
            key={ref.sha256}
            className="inline-flex items-center gap-2 text-sm text-fg-muted"
          >
            <span>
              {ref.filename} ({(ref.size / 1024).toFixed(1)} KB)
            </span>
            <a
              href={`/api/files/${ref.sha256}?filename=${encodeURIComponent(ref.filename)}`}
              download={ref.filename}
              className="text-accent hover:underline"
            >
              Download
            </a>
          </span>
        ))}
      </span>
    )
  }
  if (typeof value === 'object' && 'sha256' in (value as object)) {
    const ref = value as { filename: string; size: number; sha256: string }
    return (
      <span className="inline-flex items-center gap-2 text-sm text-fg-muted">
        <span>
          {ref.filename} ({(ref.size / 1024).toFixed(1)} KB)
        </span>
        <a
          href={`/api/files/${ref.sha256}?filename=${encodeURIComponent(ref.filename)}`}
          download={ref.filename}
          className="text-accent hover:underline"
        >
          Download
        </a>
      </span>
    )
  }
  return <span>{String(value)}</span>
}
