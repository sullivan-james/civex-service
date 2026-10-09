import type {
  UploadProgressState,
  UploadStop,
} from '../../hooks/useFileUploads'
import { formatEstimate } from '../../utils/dbFormat'
import { formatSize } from '../../utils/storage'
import { Button, ProgressBar } from '../ui'

/** Files being added to civex: which file, how far, how fast, how long is left,
 * and a way to stop. Once every byte is in it says civex is saving the file
 * (hashing and writing it takes a while for a big file), rather than sitting
 * at 100%. "Adding", not "uploading": the file goes into this computer's
 * storage; sending to the server is sync's word. */
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
            Adding file {state.index + 1} of {state.total}:{' '}
          </span>
        )}
        <span className="font-medium">{state.name}</span>
      </p>
      <ProgressBar
        fraction={pct / 100}
        label={`Adding ${state.name}`}
        busy={state.saving}
        thin
        className="w-full"
      />
      <div className="flex items-center justify-between gap-2 text-xs text-fg-muted">
        <p>
          {state.saving
            ? 'Saving to storage…'
            : `${pct}% · ${formatSize(state.loaded)} of ${formatSize(state.size)}` +
              (state.rate > 0 ? ` · ${formatSize(state.rate)}/s` : '') +
              (state.eta != null
                ? ` · ${formatEstimate(Math.round(state.eta))} left`
                : '')}
        </p>
        <Button size="sm" variant="link" onClick={onCancel}>
          Stop
        </Button>
      </div>
    </div>
  )
}

/** A batch that stopped part way: what was added, which file stopped it and
 * why, and a way to add the rest. The files that were added are already saved
 * to the record. */
export function UploadStopped({
  stop,
  onRetry,
  onDismiss,
}: {
  stop: UploadStop
  onRetry: (rest: File[]) => void
  onDismiss: () => void
}) {
  return (
    <div role="alert" className="space-y-1 text-xs">
      <p className="text-danger">
        {stop.total > 1 && `Added ${stop.added} of ${stop.total} files. `}
        Couldn&rsquo;t add <span className="break-all">{stop.name}</span>:{' '}
        {stop.message}
      </p>
      <div className="flex gap-3">
        <Button size="sm" variant="link" onClick={() => onRetry(stop.rest)}>
          {stop.rest.length > 1
            ? `Add the remaining ${stop.rest.length}`
            : 'Try again'}
        </Button>
        <Button size="sm" variant="link" onClick={onDismiss}>
          Dismiss
        </Button>
      </div>
    </div>
  )
}
