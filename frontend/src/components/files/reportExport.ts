import type { FileExportResult } from '../../api/fileAccess'

/** The one place that says what an export did, for any way of starting one:
 * how many files, how they got there (a link is the stored file itself, so it
 * says not to edit it in place), where, and what was left out. */
export function reportExport(
  toast: {
    success: (m: string, o?: { duration?: number; action?: Action }) => void
    error: (m: string) => void
  },
  result: FileExportResult,
) {
  const plural = (n: number, word: string) =>
    `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`
  const fileCount = result.copied + result.linked + result.unchanged
  const made = [
    fileCount > 0 || result.tables === 0 ? plural(fileCount, 'file') : null,
    result.tables > 0 ? plural(result.tables, 'table') : null,
  ]
    .filter(Boolean)
    .join(' and ')
  if (result.missing.length > 0)
    toast.error(
      `${plural(result.missing.length, 'file')} left out; the folder's MISSING.txt lists them.`,
    )
  const how = [
    result.linked > 0 && `${result.linked.toLocaleString()} linked`,
    result.copied > 0 && `${result.copied.toLocaleString()} copied`,
  ].filter(Boolean)
  const detail = how.length > 0 ? ` (${how.join(', ')})` : ''
  const where =
    result.location && result.location !== 'project'
      ? ` on ${result.location}`
      : ''
  const warning =
    result.linked > 0
      ? ' Linked files are the stored files themselves: don’t edit them in place.'
      : ''
  if (result.opened) {
    toast.success(`Opened a folder of ${made}${detail}${where}.${warning}`, {
      duration: warning ? 12000 : undefined,
    })
  } else {
    toast.success(
      `A folder of ${made}${detail} is ready${where} at ${result.dest}.${warning}`,
      {
        duration: 15000,
        action: {
          label: 'Copy path',
          onClick: () => void navigator.clipboard?.writeText(result.dest),
        },
      },
    )
  }
}

type Action = { label: string; onClick: () => void }
