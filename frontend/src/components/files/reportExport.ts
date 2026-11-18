import type { FileExportResult } from '../../api/fileAccess'

/** The one place that says what an export did, for any way of starting one:
 * how many files, where, how to change them when they can't be saved over (a
 * linked file is the stored file itself, so it is read-only), and what was left
 * out. */
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
  const where =
    result.location && result.location !== 'project'
      ? ` on ${result.location}`
      : ''
  // How the folder was made (links, copies) is civex's business; what matters
  // is that the linked files can be opened but not saved over.
  const warning =
    result.linked > 0
      ? ' To change these files, edit them in civex or put them on a drive.'
      : ''
  if (result.opened) {
    toast.success(`Opened a folder of ${made}${where}.${warning}`, {
      duration: warning ? 12000 : undefined,
    })
  } else {
    toast.success(
      `A folder of ${made} is ready${where} at ${result.dest}.${warning}`,
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
