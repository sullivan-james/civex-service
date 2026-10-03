import type { ReactNode } from 'react'
import type { FileRef } from '../../api/files'
import { useFileLocationDisplay } from '../../hooks/useFileLocationDisplay'
import { TriggerPopover } from '../ui'
import { AlertTriangle, HardDrive } from '../ui/icons'
import { FileInfoPanel } from './FileInfoPanel'

type FileLike = Pick<
  FileRef,
  'sha256' | 'filename' | 'resolved_filename' | 'location'
>

function whyUnavailable(file: FileLike): string {
  const where = file.location?.volume
    ? `volume '${file.location.volume}'`
    : 'its volume'
  return `This file is on ${where}, which isn't available right now.`
}

/** A link that downloads a file, or -- when the file is on a volume that can't
 * be reached -- plain text saying so, instead of a link that would fail. */
export function FileLink({
  file,
  className = '',
  title,
  children,
  whenUnavailable,
}: {
  file: FileLike
  className?: string
  title?: string
  children: ReactNode
  /** What to show in place of the link when the file can't be opened. */
  whenUnavailable?: ReactNode
}) {
  const name = file.resolved_filename ?? file.filename
  if (file.location?.available === false)
    return (
      <span
        aria-disabled="true"
        title={whyUnavailable(file)}
        className="text-fg-muted"
      >
        {whenUnavailable ?? children}
      </span>
    )
  return (
    <a
      href={`/api/files/${file.sha256}?filename=${encodeURIComponent(name)}`}
      download={name}
      className={className}
      title={title}
    >
      {children}
    </a>
  )
}

function chipText(file: FileLike): string {
  const loc = file.location
  if (!loc) return ''
  if (loc.volume === null) return 'location unknown'
  if (loc.available === false)
    return `${loc.volume} · ${loc.state.replace('_', ' ')}`
  return loc.volume
}

/** Which volume a file is stored on, shown when it matters (see
 * `useFileLocationDisplay`). In advanced mode it opens the full details: the
 * path on disk, the hash, and everything else that uses the same file. */
export function FileLocationChip({ file }: { file: FileLike }) {
  // A file with no location yet (just uploaded, not saved) has nothing to say,
  // and shouldn't subscribe to anything to find that out.
  if (!file.location) return null
  return <LocationChip file={file} />
}

function LocationChip({ file }: { file: FileLike }) {
  const { show, advanced, unavailable } = useFileLocationDisplay(file.location)
  if (!show) return null

  const tone = unavailable
    ? 'border-attention-muted bg-attention-subtle text-attention'
    : 'border-border bg-canvas-inset text-fg-muted'
  const content = (
    <>
      {unavailable ? (
        <AlertTriangle size={11} aria-hidden="true" />
      ) : (
        <HardDrive size={11} aria-hidden="true" />
      )}
      {chipText(file)}
    </>
  )
  const base = `inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${tone}`

  if (!advanced)
    return (
      <span
        className={base}
        title={
          unavailable
            ? whyUnavailable(file)
            : `Stored on volume '${file.location?.volume}'`
        }
      >
        {content}
      </span>
    )

  return (
    <TriggerPopover
      label="Where this file is stored"
      panelClassName="bg-canvas border border-border rounded-md shadow-lg"
      trigger={({ open, toggle }) => (
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          aria-haspopup="dialog"
          aria-label={`Where ${file.resolved_filename ?? file.filename} is stored: ${chipText(file)}`}
          className={`${base} cursor-pointer hover:border-border-strong`}
        >
          {content}
        </button>
      )}
    >
      <FileInfoPanel sha256={file.sha256} />
    </TriggerPopover>
  )
}
