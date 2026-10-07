import type { UploadProgressState } from '../../hooks/useFileUploads'
import { formatEstimate } from '../../utils/dbFormat'
import { formatSize } from '../../utils/storage'
import { Button, ProgressBar } from '../ui'

/** An upload in progress: which file, how far, how fast, how long is left, and
 * a way to stop. When every byte is sent it says the server is saving the file
 * (hashing and writing it takes a while for a big file), rather than sitting
 * at 100%. */
export function UploadProgress({
  state,
  onCancel,
}: {
  state: UploadProgressState
  onCancel: () => void
}) {
  const pct =
    state.size > 0
      ? Math.min(100, Math.round((state.loaded / state.size) * 100))
      : 0
  return (
    <div role="status" aria-live="polite" className="space-y-1">
      <p className="break-all text-xs text-fg">
        {state.total > 1 && (
          <span className="text-fg-muted">
            File {state.index + 1} of {state.total}:{' '}
          </span>
        )}
        <span className="font-medium">{state.name}</span>
      </p>
      <ProgressBar
        fraction={pct / 100}
        label={`Uploading ${state.name}`}
        busy={state.saving}
        thin
        className="w-full"
      />
      <div className="flex items-center justify-between gap-2 text-xs text-fg-muted">
        <p>
          {state.saving
            ? 'Sent. Saving to storage…'
            : `${pct}% · ${formatSize(state.loaded)} of ${formatSize(state.size)}` +
              (state.rate > 0 ? ` · ${formatSize(state.rate)}/s` : '') +
              (state.eta != null
                ? ` · ${formatEstimate(Math.round(state.eta))} left`
                : '')}
        </p>
        <Button size="sm" variant="link" onClick={onCancel}>
          Cancel upload
        </Button>
      </div>
    </div>
  )
}
