import { Link } from 'react-router'
import { Badge } from '../ui'
import { useRecord } from '../../hooks/useRecords'
import type { Field } from '../../api/schemas'

function ReferenceLink({ id }: { id: string }) {
  const { data: record, isError } = useRecord(id)
  if (isError) {
    return (
      <span
        className="font-mono text-fg-subtle line-through"
        title="Referenced record not found (deleted?)"
      >
        {id.slice(0, 8)}
      </span>
    )
  }
  return (
    <Link to={`/records/${id}`} className="text-accent hover:underline">
      {record?.natural_name ?? (
        <span className="font-mono">{id.slice(0, 8)}</span>
      )}
    </Link>
  )
}

export function FieldValue({
  value,
  field,
}: {
  value: unknown
  field?: Pick<Field, 'type'>
}) {
  if (value === null || value === undefined)
    return <span className="text-fg-subtle">—</span>
  if (field?.type === 'reference' && typeof value === 'string') {
    return <ReferenceLink id={value} />
  }
  if (field?.type === 'reference_list' && Array.isArray(value)) {
    if (value.length === 0) return <span className="text-fg-subtle">—</span>
    return (
      <span className="flex flex-wrap gap-x-2 gap-y-1">
        {(value as string[]).map((id) => (
          <ReferenceLink key={id} id={id} />
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
