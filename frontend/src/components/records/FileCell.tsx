import type { FileRef } from '../../api/files'
import { formatSize } from '../../utils/storage'
import { Paperclip } from '../ui/icons'
import { FileLink, FileLocationChip } from './FileLocation'
import { fileRefsIn } from '../../utils/fileRefs'

function nameOf(ref: FileRef): string {
  return ref.resolved_filename ?? ref.filename
}

/** A file or list of files on one line of a table: the first file's name
 * (a download), its size, or how many more there are, and where it is when
 * that needs saying. Every name and size is on hover. */
export function FileCell({ value }: { value: unknown }) {
  const refs = fileRefsIn(value)
  if (refs.length === 0) return <span className="text-fg-subtle">—</span>
  const [first, ...rest] = refs
  const total = refs.reduce((sum, r) => sum + (r.size ?? 0), 0)
  const hover = refs.map((r) => `${nameOf(r)} (${formatSize(r.size)})`)
  return (
    <span
      className="inline-flex max-w-xs items-center gap-1.5 align-middle"
      title={
        rest.length
          ? `${refs.length} files, ${formatSize(total)}\n${hover.join('\n')}`
          : hover[0]
      }
    >
      <Paperclip className="h-3.5 w-3.5 shrink-0 text-fg-subtle" aria-hidden />
      <FileLink
        file={first}
        className="min-w-0 truncate text-accent hover:underline"
      >
        {nameOf(first)}
      </FileLink>
      <span className="shrink-0 text-xs text-fg-muted">
        {rest.length ? `+${rest.length} more` : formatSize(first.size)}
      </span>
      <FileLocationChip file={first} />
    </span>
  )
}
