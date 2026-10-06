import { useState } from 'react'
import {
  useHistoryStorage,
  useReclaimHistoryStorage,
} from '../../../hooks/useAudit'
import { errorMessage } from '../../../lib/errors'
import { formatBytes } from '../../../utils/format'
import { Button, Card, ConfirmDialog, ProgressBar } from '../../ui'

/** How history is stored: older history being converted to what-changed form
 * (in the background, by itself), and the room in the database file that is no
 * longer used, which a person can give back to the disk. */
export function HistoryStorageCard() {
  const { data } = useHistoryStorage()
  const reclaim = useReclaimHistoryStorage()
  const [confirm, setConfirm] = useState(false)
  if (!data) return null
  const free = data.free_bytes ?? 0
  const worthIt = free > 1024 * 1024 // a megabyte or more

  return (
    <Card title="History storage">
      <div className="space-y-3 text-sm">
        {data.converting && data.total ? (
          <div className="flex flex-wrap items-center gap-3">
            <ProgressBar
              fraction={(data.done ?? 0) / data.total}
              label="History converted"
            />
            <span className="text-fg-muted">
              Storing older history more compactly:{' '}
              {(data.done ?? 0).toLocaleString()} of{' '}
              {data.total.toLocaleString()} changes. The project can be used
              meanwhile.
            </span>
          </div>
        ) : data.whole_entries > 0 ? (
          <p className="text-fg-muted">
            {data.whole_entries.toLocaleString()} older changes will be stored
            more compactly next time the server starts.
          </p>
        ) : (
          <p className="text-fg-muted">History is stored compactly.</p>
        )}
        {data.size_bytes != null && (
          <div className="flex flex-wrap items-center gap-3">
            <span>
              Database file: {formatBytes(data.size_bytes)}
              {free > 0 && (
                <span className="text-fg-muted">
                  {' '}
                  ({formatBytes(free)} no longer used)
                </span>
              )}
            </span>
            {worthIt && (
              <Button
                size="sm"
                disabled={data.converting || reclaim.isPending}
                onClick={() => setConfirm(true)}
              >
                Reclaim space
              </Button>
            )}
          </div>
        )}
        {reclaim.error && (
          <p role="alert" className="text-xs text-danger">
            {errorMessage(reclaim.error)}
          </p>
        )}
      </div>
      {confirm && (
        <ConfirmDialog
          title="Give unused room back to the disk?"
          body={`The database file is rewritten without the ${formatBytes(free)} it no longer uses. It needs about ${formatBytes(data.size_bytes ?? 0)} of free disk while it runs, and the project waits for it to finish.`}
          confirmLabel="Reclaim space"
          isPending={reclaim.isPending}
          onConfirm={() =>
            reclaim.mutate(undefined, { onSettled: () => setConfirm(false) })
          }
          onClose={() => setConfirm(false)}
        />
      )}
    </Card>
  )
}
