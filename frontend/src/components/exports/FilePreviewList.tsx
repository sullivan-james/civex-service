import type { FilePreview } from '../../api/fileAccess'
import { pathsToRows } from '../../utils/fileTree'
import { formatSize } from '../../utils/storage'
import { ToDownloadNotice } from '../files/ToDownloadNotice'
import { UnreachableList } from '../files/UnreachableList'
import { FileTree } from './FileTree'

const plural = (n: number, word: string) =>
  `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`

/** What an export would make, as one folder tree: the stored files and the tables
 * the export writes, each in the place it will be, with how many files, how big,
 * and any that can't be reached (which drive, what to do). What a person checks before saving or running an export. */
export function FilePreviewList({ data }: { data: FilePreview }) {
  // Whatever the server sent, a preview never breaks the dialog it sits in.
  const items = data.items ?? []
  const tables = data.tables ?? []
  const total = data.total ?? items.length
  const toFetch = data.to_fetch?.files ?? 0
  const missing = total - (data.available ?? total) - toFetch
  const rows = pathsToRows([
    ...items,
    ...tables.map((t) => ({ path: t.path, rows: t.rows })),
  ])
  const empty = items.length === 0 && tables.length === 0
  return (
    <div className="space-y-2">
      <p className="text-sm text-fg-muted">
        {[
          plural(total, 'file') + ` (${formatSize(data.bytes ?? 0)})`,
          tables.length > 0 ? plural(tables.length, 'table') : null,
        ]
          .filter(Boolean)
          .join(' · ')}
        .
      </p>
      {missing > 0 && (
        // Said before anything is made, with which drive and what to do, so a
        // drive can be plugged in first; the preview follows when it changes.
        <section
          aria-label="Files that can’t be reached"
          className="rounded-md border border-attention-muted bg-attention-subtle px-3 py-2"
        >
          <p className="mb-2 text-sm font-medium text-fg">
            {plural(missing, 'file')} can’t be reached right now
          </p>
          <UnreachableList groups={data.unavailable ?? []} />
        </section>
      )}
      <ToDownloadNotice toFetch={data.to_fetch} />
      {empty ? (
        <p className="text-sm text-fg-muted">
          Nothing to export yet. Records added later are included.
        </p>
      ) : (
        <div className="max-h-80 overflow-y-auto rounded-md border border-border bg-canvas p-3">
          <FileTree collapsible label="Folder preview" rows={rows} />
          {total > items.length && (
            <p className="mt-2 border-t border-border pt-2 text-xs text-fg-muted">
              … and {(total - items.length).toLocaleString()} more files
            </p>
          )}
        </div>
      )}
    </div>
  )
}
