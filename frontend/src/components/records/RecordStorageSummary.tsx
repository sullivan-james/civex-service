import { Link } from 'react-router'
import { useFileListing } from '../../hooks/useFileListing'
import { placeLabel } from '../../utils/places'
import { MoveToDriveButton } from '../files/MoveDialog'
import { AlertTriangle, HardDrive } from '../ui/icons'

/** Where a record's files are, with everything beneath it: how many are on
 * each drive (the same places the record's **Their files** shows), what can't
 * be opened right now, and **Move to drive…** for all of them. `filesHref`
 * opens them listed one by one (the Contains tab's files), when the record
 * contains anything. */
export function RecordStorageSummary({
  recordId,
  name,
  filesHref,
}: {
  recordId: string
  name: string
  filesHref?: string
}) {
  const pick = { within: recordId }
  const { data } = useFileListing({ ...pick, limit: 1 })
  const places = data?.summary ?? []
  const files = places.reduce((n, p) => n + p.files, 0)
  if (files === 0) return null
  const unreachable = places
    .filter((p) => p.kind === 'unreachable' || p.kind === 'missing')
    .reduce((n, p) => n + p.files, 0)

  return (
    <div
      aria-label="Where this record's files are stored"
      role="group"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-border bg-canvas-subtle px-3 py-2 text-xs text-fg-muted"
    >
      <span className="inline-flex items-center gap-1.5">
        <HardDrive size={13} aria-hidden="true" />
        {files.toLocaleString()} {files === 1 ? 'file' : 'files'}
        {filesHref ? ', with what it contains,' : ''} on{' '}
        {places
          .map((p) => `${placeLabel(p)} (${p.files.toLocaleString()})`)
          .join(', ')}
      </span>
      {unreachable > 0 && (
        <span className="inline-flex items-center gap-1 text-attention">
          <AlertTriangle size={12} aria-hidden="true" />
          {unreachable.toLocaleString()} can't be opened right now
        </span>
      )}
      <span className="ml-auto flex items-center gap-2">
        {filesHref && (
          <Link to={filesHref} className="text-accent hover:underline">
            Show all files
          </Link>
        )}
        <MoveToDriveButton what={`${name}'s files`} pick={pick} />
      </span>
    </div>
  )
}
