import { formatSize } from '../../utils/storage'

/** Said before anything is made: some of the files are only on the server and
 * will be downloaded first (their progress then shows in the status bar, as
 * part of the same job). The one wording, for an export's preview, the
 * export's dialog and the Files tab's actions. */
export function ToDownloadNotice({
  toFetch,
}: {
  toFetch: { files: number; bytes: number } | undefined | null
}) {
  if (!toFetch || toFetch.files === 0) return null
  const n = toFetch.files
  return (
    <p
      role="status"
      className="rounded-md border border-accent-muted bg-accent-subtle px-3 py-2 text-sm text-fg"
    >
      {n.toLocaleString()} file{n === 1 ? '' : 's'}
      {toFetch.bytes > 0 ? ` (${formatSize(toFetch.bytes)})` : ''}{' '}
      {n === 1 ? "isn't" : "aren't"} on this computer yet:{' '}
      {n === 1 ? 'it is' : 'they are'} downloaded from the server first. You can
      follow the download in the status bar.
    </p>
  )
}
