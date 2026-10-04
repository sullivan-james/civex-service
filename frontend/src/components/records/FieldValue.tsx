import type { FileRef } from '../../api/files'
import { FileLink, FileLocationChip } from './FileLocation'
import { Badge } from '../ui'
import { ReferenceLink } from './ReferenceLink'
import { useFieldTimeZone } from './timeZoneContext'
import { formatDateTime } from '../../utils/dates'
import { formatLocation, isGeometry } from '../../utils/geo'
import { describeGeometry } from '../../utils/geoDraft'
import type { Field } from '../../api/schemas'

export function FieldValue({
  value,
  field,
  referenceLabels,
  referenceCollections,
}: {
  value: unknown
  /** Reference/reference_list values render as links; every other type
   * falls back to the existing shape-based rendering below. */
  field?: Field
  referenceLabels?: Record<string, string | null> | null
  referenceCollections?: Record<string, string> | null
}) {
  const timeZone = useFieldTimeZone(field)
  if (value === null || value === undefined)
    return field?.type === 'geo' ? (
      <span className="text-fg-subtle">
        Not set. Click to enter latitude, longitude.
      </span>
    ) : (
      <span className="text-fg-subtle">—</span>
    )
  if (field?.type === 'longtext' && typeof value === 'string')
    return <span className="whitespace-pre-wrap">{value}</span>
  if (field?.type === 'datetime' && typeof value === 'string' && value)
    // Shown as wall time in the field's zone; the stored UTC value is on hover.
    return <span title={value}>{formatDateTime(value, timeZone)}</span>
  if (field?.type === 'geo' && isGeometry(value))
    // Full GeoJSON on hover; plain points read as "latitude, longitude".
    return (
      <span title={JSON.stringify(value)}>
        {value.type === 'Point'
          ? formatLocation(value)
          : describeGeometry(value)}
      </span>
    )
  if (
    field?.type === 'float' &&
    typeof field.restrictions?.unit === 'string' &&
    typeof value === 'number'
  )
    return (
      <span>
        {value} <span className="text-fg-muted">{field.restrictions.unit}</span>
      </span>
    )
  if (field?.type === 'reference' && typeof value === 'string')
    return (
      <ReferenceLink
        id={value}
        labels={referenceLabels}
        collections={referenceCollections}
      />
    )
  if (field?.type === 'reference_list' && Array.isArray(value)) {
    if (value.length === 0) return <span className="text-fg-subtle">—</span>
    return (
      <span className="flex flex-wrap gap-x-2 gap-y-1">
        {(value as string[]).map((id) => (
          <ReferenceLink
            key={id}
            id={id}
            labels={referenceLabels}
            collections={referenceCollections}
          />
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
    const refs = value as FileRef[]
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
            <FileLink
              file={ref}
              className="text-accent hover:underline"
              whenUnavailable={
                <span className="text-fg-subtle">Unavailable</span>
              }
            >
              Download
            </FileLink>
            <FileLocationChip file={ref} />
          </span>
        ))}
      </span>
    )
  }
  if (typeof value === 'object' && 'sha256' in (value as object)) {
    const ref = value as FileRef
    return (
      <span className="inline-flex items-center gap-2 text-sm text-fg-muted">
        <span>
          {ref.filename} ({(ref.size / 1024).toFixed(1)} KB)
        </span>
        <FileLink
          file={ref}
          className="text-accent hover:underline"
          whenUnavailable={<span className="text-fg-subtle">Unavailable</span>}
        >
          Download
        </FileLink>
        <FileLocationChip file={ref} />
      </span>
    )
  }
  return <span>{String(value)}</span>
}
