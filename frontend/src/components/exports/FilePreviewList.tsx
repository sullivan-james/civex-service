import type { FilePreview } from '../../api/fileAccess'
import { pathsToRows } from '../../utils/fileTree'
import { formatSize } from '../../utils/storage'
import { ToDownloadNotice } from '../files/ToDownloadNotice'
import { FileTree } from './FileTree'

const plural = (n: number, word: string) =>
  `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`

/** What an export would make, as one folder tree: the stored files and the tables
 * the export writes, each in the place it will be, with how many files, how big,
 * and where they are. What a person checks before saving or running an export. */
export function FilePreviewList({ data }: { data: FilePreview }) {
  // Whatever the server sent, a preview never breaks the dialog it sits in.
  const items = data.items ?? []
  const tables = data.tables ?? []
  const byVolume = data.by_volume ?? []
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
        {byVolume.length > 0 && (
          <>
            {' '}
            on{' '}
            {byVolume
              .map((v) => `${v.volume} (${v.files.toLocaleString()})`)
              .join(', ')}
          </>
        )}
        .
        {data.scattered &&
          ' They are on several drives, so a linked folder can’t hold them; you can move them onto one or copy them.'}
        {missing > 0 &&
          ` ${plural(missing, 'file')} can’t be reached right now.`}
      </p>
      <ToDownloadNotice toFetch={data.to_fetch} />
      {empty ? (
        <p className="text-sm text-fg-muted">There is nothing to export.</p>
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
