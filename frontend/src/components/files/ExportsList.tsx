import { useState } from 'react'
import type { ExportInfo } from '../../api/fileAccess'
import { useExports, useRemoveExports } from '../../hooks/useFileAccess'
import { errorMessage } from '../../lib/errors'
import { formatSize } from '../../utils/storage'
import {
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Spinner,
  useToast,
} from '../ui'

const where = (e: ExportInfo) =>
  e.location === 'project' ? 'The project folder' : e.location

function describe(e: ExportInfo): string {
  const parts = [`${e.files.toLocaleString()} files`]
  if (e.linked != null && e.copied != null) {
    if (e.linked > 0) parts.push(`${e.linked.toLocaleString()} linked`)
    if (e.copied > 0) parts.push(`${e.copied.toLocaleString()} copied`)
    parts.push(
      e.bytes_on_disk
        ? `${formatSize(e.bytes_on_disk)} on disk`
        : 'no space used',
    )
  }
  if (e.updated) parts.push(`updated ${new Date(e.updated).toLocaleString()}`)
  return parts.join(' · ')
}

/** The folders earlier exports made, where they are and what they cost, with a
 * way to remove them. A linked folder gives back no space and removing it leaves
 * the stored files alone; a copied one gives back what it holds. Anything of
 * yours inside an export folder is left. */
export function ExportsList() {
  const toast = useToast()
  const { data: exports, isLoading, error } = useExports()
  const remove = useRemoveExports()
  const [confirming, setConfirming] = useState<ExportInfo[] | null>(null)

  function run(targets: ExportInfo[]) {
    remove.mutate(
      targets.map((t) => t.path),
      {
        onSuccess: ({ results, errors }) => {
          const freed = results.reduce((n, r) => n + r.freed_bytes, 0)
          const kept = results.reduce((n, r) => n + r.kept_files, 0)
          if (results.length > 0)
            toast.success(
              `Removed ${results.length.toLocaleString()} ${results.length === 1 ? 'export' : 'exports'}` +
                (freed > 0 ? `, freeing ${formatSize(freed)}` : '') +
                (kept > 0
                  ? `. ${kept.toLocaleString()} of your own files were left in place.`
                  : '.'),
            )
          if (errors.length > 0)
            toast.error(`${errors[0].path}: ${errors[0].error}`)
          setConfirming(null)
        },
        onError: (err) => {
          toast.error(errorMessage(err))
          setConfirming(null)
        },
      },
    )
  }

  const list = exports ?? []
  const reclaimable = list.reduce((n, e) => n + (e.bytes_on_disk ?? 0), 0)

  return (
    <Card
      title="Exports"
      count={list.length}
      action={
        list.length > 1 ? (
          <Button
            size="sm"
            variant="danger"
            disabled={remove.isPending}
            onClick={() => setConfirming(list)}
          >
            Remove all {list.length}
          </Button>
        ) : undefined
      }
    >
      {isLoading && <Spinner />}
      {error && <ErrorState message={errorMessage(error)} />}
      {exports && list.length === 0 && (
        <EmptyState
          title="No exports"
          message="Folders made with Files → Open in folder or Copy to a drive appear here."
        />
      )}
      {list.length > 0 && (
        <>
          <p className="mb-3 text-sm text-fg-muted">
            {reclaimable > 0
              ? `Copies are using ${formatSize(reclaimable)}. `
              : 'These take no space. '}
            Removing a linked folder never touches the stored files.
          </p>
          <ul className="divide-y divide-border rounded-md border border-border">
            {list.map((e) => (
              <li
                key={e.path}
                className="flex items-center justify-between gap-3 px-3 py-2"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-fg">
                    {e.name}{' '}
                    <span className="font-normal text-fg-muted">
                      on {where(e)}
                    </span>
                  </p>
                  <p className="text-xs text-fg-muted">{describe(e)}</p>
                </div>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={remove.isPending}
                  onClick={() => setConfirming([e])}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="mt-3 text-xs text-fg-muted">
        Exports on a drive that isn’t connected aren’t listed until you plug it
        in.
      </p>
      {confirming && (
        <ConfirmDialog
          title={
            confirming.length === 1
              ? `Remove “${confirming[0].name}”?`
              : `Remove ${confirming.length} exports?`
          }
          body={
            <p>
              The folders and the links or copies in them are deleted. Links
              give back no space and the stored files are not touched; copies
              give back their space. Anything of your own inside an export
              folder is kept.
            </p>
          }
          confirmLabel="Remove"
          variant="danger"
          isPending={remove.isPending}
          onConfirm={() => run(confirming)}
          onClose={() => setConfirming(null)}
        />
      )}
    </Card>
  )
}
