interface FileRef {
  sha256: string
  filename: string
  size: number
}

interface Props {
  value: unknown
  owner: string
  repo: string
}

function fmtSize(bytes: number): string {
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`
  return `${(bytes / 1024).toFixed(1)} KB`
}

function isFileRef(v: unknown): v is FileRef {
  return typeof v === 'object' && v !== null && 'sha256' in v && 'filename' in v
}

export function FieldValue({ value, owner, repo }: Props) {
  if (value === null || value === undefined) {
    return <span className="text-gray-400">—</span>
  }

  if (typeof value === 'boolean') {
    return (
      <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium ${value ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
        {String(value)}
      </span>
    )
  }

  if (Array.isArray(value) && value.length > 0 && isFileRef(value[0])) {
    return (
      <span className="flex flex-col gap-0.5">
        {(value as FileRef[]).map(ref => (
          <FileRefLink key={ref.sha256} ref_={ref} owner={owner} repo={repo} />
        ))}
      </span>
    )
  }

  if (isFileRef(value)) {
    return <FileRefLink ref_={value as FileRef} owner={owner} repo={repo} />
  }

  return <span>{String(value)}</span>
}

function FileRefLink({ ref_, owner, repo }: { ref_: FileRef; owner: string; repo: string }) {
  const url = `/api/v1/repos/${owner}/${repo}/objects/${ref_.sha256}?filename=${encodeURIComponent(ref_.filename)}`
  return (
    <span className="inline-flex items-center gap-2 text-sm text-gray-600">
      <span>{ref_.filename} ({fmtSize(ref_.size)})</span>
      <a href={url} download={ref_.filename} className="text-blue-600 hover:underline text-xs">
        Download
      </a>
    </span>
  )
}
