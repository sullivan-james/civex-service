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
            This cancels every workflow run that is waiting, stops the ones
            running before their next step, and pauses automation: edits
            won&apos;t start workflows and manual runs are refused until you
            resume.
          </p>
          <p className="text-fg-muted">
            Use it when workflows keep triggering each other. A step already in
            progress finishes (or times out) first. Nothing already done is
            undone.
          </p>
        </div>
      }
      warning={stop.error ? errorMessage(stop.error) : undefined}
      onConfirm={() => stop.mutate(undefined, { onSuccess: onClose })}
      onClose={onClose}
    />
  )
}
