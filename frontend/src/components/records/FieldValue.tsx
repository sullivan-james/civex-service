import { Badge } from '../ui'

export function FieldValue({ value }: { value: unknown }) {
  if (value === null || value === undefined)
    return <span className="text-fg-subtle">—</span>
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
