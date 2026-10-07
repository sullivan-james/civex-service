import { useStopAutomation } from '../../hooks/useWorkflows'
import { errorMessage } from '../../lib/errors'
import { ConfirmDialog } from '../ui'

/** Stop all automation: the one confirmation behind every Stop button, so what
 * it does is said once, in the same words, wherever it is asked for. */
export function StopAutomationDialog({ onClose }: { onClose: () => void }) {
  const stop = useStopAutomation()
  return (
    <ConfirmDialog
      title="Stop all automation?"
      confirmLabel="Stop automation"
      variant="danger"
      isPending={stop.isPending}
      body={
        <div className="space-y-2 text-sm">
          <p>
            Cancels waiting runs, stops running ones before their next step, and
            pauses automation until you resume. Nothing already done is undone.
          </p>
        </div>
      }
      warning={stop.error ? errorMessage(stop.error) : undefined}
      onConfirm={() => stop.mutate(undefined, { onSuccess: onClose })}
      onClose={onClose}
    />
  )
}
