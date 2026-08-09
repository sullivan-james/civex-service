import { useState } from 'react'
import { type WorkflowJob } from '../../api/workflows'
import { Badge, Button } from '../ui'
import { ChevronDown, ChevronUp } from '../ui/icons'
import { explainFailure } from '../../utils/runNarrative'

export default function FailureExplanation({ job }: { job: WorkflowJob }) {
  const [showTechnical, setShowTechnical] = useState(false)
  const { headline, whatToDo, step, retryable } = explainFailure(
    job.error_details,
  )

  return (
    <div className="border border-danger-subtle-border rounded-md bg-danger-subtle p-4 space-y-2">
      <h2 className="text-sm font-semibold text-danger">{headline}</h2>
      <p className="text-sm text-fg">
        {whatToDo}
        {step && (
          <span className="text-fg-muted"> (failed at step "{step}")</span>
        )}
      </p>
      {retryable && <Badge variant="default">safe to retry</Badge>}

      <div>
        <Button
          size="sm"
          variant="default"
          onClick={() => setShowTechnical((s) => !s)}
        >
          {showTechnical ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          {showTechnical ? 'Hide technical error' : 'Show technical error'}
        </Button>
        {showTechnical && (
          <pre className="mt-2 text-xs text-danger whitespace-pre-wrap font-mono bg-canvas rounded-md p-3 border border-danger-subtle-border">
            {job.error ?? 'No error details recorded.'}
          </pre>
        )}
      </div>
    </div>
  )
}
