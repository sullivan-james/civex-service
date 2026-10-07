import { useEffect, useState, type MouseEvent, type ReactNode } from 'react'
import { Link } from 'react-router'
import type { FileRef } from '../../api/files'
import { useFileLocationDisplay } from '../../hooks/useFileLocationDisplay'
import { formatSize } from '../../utils/storage'
import { PlaceStatus, VolumeStatus } from '../files/Where'
import { Button, Chip, TriggerPopover } from '../ui'
import { AlertTriangle, HardDrive } from '../ui/icons'
import { FileInfoPanel } from './FileInfoPanel'

type FileLike = Pick<
  FileRef,
  'sha256' | 'filename' | 'resolved_filename' | 'location'
> &
  Partial<Pick<FileRef, 'size'>>

function whyUnavailable(file: FileLike): string {
  const where = file.location?.volume
    ? `volume '${file.location.volume}'`
    : 'its volume'
  const fix = file.location?.fix
  return `This file is on ${where}, which isn't available right now.${fix ? ` ${fix}` : ''}`
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
    <DownloadLink file={file} className={className} title={title}>
      {children}
    </DownloadLink>
  )
}

/** The download link for a file that looked reachable when the page loaded.
 * A drive can be unplugged after that, and the browser would then show only a
 * generic "failed" in its downloads. So a plain click first asks the server
 * (headers only) and, if it can't be served, says why right here, in the
 * server's own words, which name the drive and what to do. Otherwise the
 * browser downloads it as usual, and it says so. Modified clicks (open in a new
 * tab, save as) are left to the browser. */
function DownloadLink({
  file,
  className,
  title,
  children,
}: {
  file: FileLike
  className: string
  title?: string
  children: ReactNode
}) {
  // error: it failed (red, stays); attention: a situation the server
  // explains, such as a file not here yet or its drive unplugged (amber,
  // stays); info: what is happening (fades).
  const [note, setNote] = useState<{
    tone: 'error' | 'attention' | 'info'
    text: string
  } | null>(null)
  const name = file.resolved_filename ?? file.filename
  const href = `/api/files/${file.sha256}?filename=${encodeURIComponent(name)}`

  useEffect(() => {
    if (!note || note.tone !== 'info') return
    const timer = setTimeout(() => setNote(null), 6000)
    return () => clearTimeout(timer)
  }, [note])

  async function onClick(e: MouseEvent<HTMLAnchorElement>) {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)
      return
    e.preventDefault()
    setNote(
      file.location?.state === 'remote'
        ? { tone: 'info', text: 'Downloading it from the server first…' }
        : null,
    )
    const abort = new AbortController()
    try {
      const res = await fetch(href, { signal: abort.signal })
      if (!res.ok) {
        const body = await res.json().catch(() => null)
        setNote({
          tone:
            res.status === 404 || res.status === 503 ? 'attention' : 'error',
          text:
            body?.detail ?? `The file couldn't be downloaded (${res.status}).`,
        })
        return
      }
      abort.abort() // only the headers were wanted; the browser fetches the rest
    } catch {
      setNote({
        tone: 'error',
        text: "Couldn't reach the server to download this.",
      })
      return
    }
    const link = document.createElement('a')
    link.href = href
    link.download = name
    link.click()
    setNote({
      tone: 'info',
      text: "Download started. It's in your browser's downloads.",
    })
  }

  return (
    <>
      <a
        href={href}
        download={name}
        className={className}
        title={title}
        onClick={onClick}
      >
        {children}
      </a>
      {note && (
        <span
          role={note.tone === 'error' ? 'alert' : 'status'}
          className={`text-xs ${
            note.tone === 'error'
              ? 'text-danger'
              : note.tone === 'attention'
                ? 'text-attention'
                : 'text-fg-muted'
          }`}
        >
          {note.text}
        </span>
      )}
    </>
  )
}

function chipText(file: FileLike): string {
  const loc = file.location
  if (!loc) return ''
  if (loc.state === 'remote') return 'not on this computer'
  if (loc.volume === null) return 'location unknown'
  if (loc.available === false)
    return `${loc.volume} · ${loc.state.replace('_', ' ')}`
  return loc.volume
}

/** What the chip says on hover, before anything is clicked: where, whether it
 * is there, and that there is more. */
function hint(file: FileLike): string {
  const loc = file.location
  if (loc?.state === 'remote')
    return 'Not downloaded to this computer yet: opening it downloads it.'
  if (!loc || loc.volume === null)
    return 'Not found on any drive yet. Click for details.'
  if (loc.available === false)
    return `On '${loc.volume}', which can't be reached now. Click for what to do.`
  return `On '${loc.volume}'. Click for details.`
}

/** Which volume a file is stored on, shown when it matters (see
 * `useFileLocationDisplay`). Clicking it (or pressing Enter) says where the
 * file is and whether it can be opened, and, if its drive isn't there, which
 * drive to plug in. **More details** adds the path on disk, every copy, the
 * hash and everything else that uses the same file. */
export function FileLocationChip({ file }: { file: FileLike }) {
  // A file with no location yet (just uploaded, not saved) has nothing to say,
  // and shouldn't subscribe to anything to find that out.
  if (!file.location) return null
  return <LocationChip file={file} />
}

function LocationChip({ file }: { file: FileLike }) {
  const { show, advanced, unavailable } = useFileLocationDisplay(file.location)
  if (!show) return null
  const name = file.resolved_filename ?? file.filename

  return (
    <TriggerPopover
      label="Where this file is stored"
      panelClassName="bg-canvas border border-border rounded-md shadow-lg"
      trigger={({ open, toggle }) => (
        <Chip
          onClick={toggle}
          aria-expanded={open}
          aria-haspopup="dialog"
          aria-label={`Where ${name} is stored: ${chipText(file)}`}
          title={hint(file)}
          warning={unavailable}
          className="shrink-0"
        >
          {unavailable ? (
            <AlertTriangle size={11} aria-hidden="true" />
          ) : (
            <HardDrive size={11} aria-hidden="true" />
          )}
          {chipText(file)}
        </Chip>
      )}
    >
      <FileLocationPanel file={file} startOpen={advanced} />
    </TriggerPopover>
  )
}

/** The answer to "where is this file, and can I get at it?", in plain words,
 * with the technical detail one click away. */
function FileLocationPanel({
  file,
  startOpen,
}: {
  file: FileLike
  startOpen: boolean
}) {
  const [more, setMore] = useState(startOpen)
  const loc = file.location
  if (!loc) return null
  const name = file.resolved_filename ?? file.filename

  return (
    <div className="w-96 max-w-full text-sm">
      <div className="space-y-3 p-3">
        <div>
          <p className="break-all font-medium text-fg">{name}</p>
          {file.size != null && !more && (
            <p className="text-xs text-fg-muted">{formatSize(file.size)}</p>
          )}
        </div>

        <p className="flex flex-wrap items-center gap-2 text-fg">
          {loc.state === 'remote' ? (
            <PlaceStatus
              place=""
              kind="server"
              reason="Another device added it. Opening or exporting it downloads it."
            />
          ) : loc.volume === null ? (
            <PlaceStatus
              place=""
              kind="missing"
              reason="It isn't on any drive Civex knows about here."
            />
          ) : (
            <>
              On <strong>{loc.volume}</strong>
              <VolumeStatus
                state={loc.state}
                reason={loc.reason}
                fix={loc.fix}
              />
            </>
          )}
        </p>
        {loc.available === false && loc.volume && (
          <Link
            to={`/settings/storage/volumes/${encodeURIComponent(loc.volume)}`}
            className="inline-block text-accent hover:underline"
          >
            Open &lsquo;{loc.volume}&rsquo;
          </Link>
        )}

        {!more && (
          <Button size="sm" variant="link" onClick={() => setMore(true)}>
            More details
          </Button>
        )}
      </div>
      {more && (
        <div className="border-t border-border">
          <FileInfoPanel sha256={file.sha256} />
        </div>
      )}
    </div>
  )
}
