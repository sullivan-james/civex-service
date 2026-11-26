import { Link } from 'react-router'
import { useHostedFiles } from '../../hooks/useFeatures'
import { useFileListing } from '../../hooks/useFileListing'
import { placeCount } from '../../utils/places'
import { MoveToDriveButton } from '../files/MoveDialog'
import { HardDrive } from '../ui/icons'

/** Where a record's files are, with everything beneath it, shown only when
 * some can't be reached or are missing: how many are in
 * each place (the same places the record's **Their files** shows, said as a
 * sentence: "10 on archive · 2 not on this computer"), and **Change storage drive…**
 * for all of them. `filesHref` opens them listed one by one (the Contains
 * tab's files), when the record contains anything. */
export function RecordStorageSummary({
  recordId,
  name,
  filesHref,
}: {
  recordId: string
  name: string
  filesHref?: string
}) {
  const hosted = useHostedFiles()
  const pick = { within: recordId }
  const { data } = useFileListing({ ...pick, limit: 1 })
  const places = data?.summary ?? []
  const files = places.reduce((n, p) => n + p.files, 0)
  const attention = places.some(
    (p) => p.kind === 'unreachable' || p.kind === 'missing',
  )
  // Said only when it matters: a file that can't be reached or is missing.
  // Where files are, when all is well, is under Files in the page's menu.
  if (files === 0 || !attention) return null
  if (hosted) {
    // No drives here: only how many aren't on the hub yet or can't be had now.
    const n = (kind: string) =>
      places.filter((p) => p.kind === kind).reduce((a, p) => a + p.files, 0)
    const missing = n('missing')
    const unreachable = n('unreachable')
    return (
      <div
        role="status"
        className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-border bg-canvas-subtle px-3 py-2 text-xs text-attention"
      >
        {missing > 0 && (
          <span>
            {missing.toLocaleString()} {missing === 1 ? 'file is' : 'files are'}{' '}
            not on the hub yet.
          </span>
        )}
        {unreachable > 0 && (
          <span>
            {unreachable.toLocaleString()}{' '}
            {unreachable === 1 ? 'file is' : 'files are'} temporarily
            unavailable. Try again shortly.
          </span>
        )}
        {filesHref && (
          <Link to={filesHref} className="ml-auto text-accent hover:underline">
            Show all files
          </Link>
        )}
      </div>
    )
  }

  return (
    <div
      aria-label="Where this record's files are stored"
      role="group"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-border bg-canvas-subtle px-3 py-2 text-xs text-fg-muted"
    >
      <span
        className={`inline-flex items-center gap-1.5 ${attention ? 'text-attention' : ''}`}
      >
        <HardDrive size={13} aria-hidden="true" />
        {files.toLocaleString()} {files === 1 ? 'file' : 'files'}
        {filesHref ? ' here and in what it contains' : ''}:{' '}
        {places.map(placeCount).join(' · ')}
      </span>
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
