import { useState } from 'react'
import { type StepExecution } from '../../api/workflows'
import { Badge } from '../ui'

function StatusBadge({ status }: { status: StepExecution['status'] }) {
  switch (status) {
    case 'success':
      return <Badge variant="success">✓ success</Badge>
    case 'failed':
      return <Badge variant="danger">✗ failed</Badge>
    default:
      return <Badge variant="default">⏭ skipped</Badge>
  }
}

function duration(seconds: number): string {
  return seconds < 60
    ? `${seconds.toFixed(2)}s`
    : `${(seconds / 60).toFixed(2)}m`
}

export default function StepExecutionCard({ step }: { step: StepExecution }) {
  const [open, setOpen] = useState(step.status === 'failed')
  const hasInputs = step.inputs && Object.keys(step.inputs).length > 0
  const hasOutputs = step.outputs && Object.keys(step.outputs).length > 0

  return (
    <div className="rounded-md border border-border bg-canvas overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-canvas-subtle transition-colors"
      >
        <span className="font-mono text-sm text-fg">{step.step_id}</span>
        <span className="text-xs text-fg-muted font-mono">{step.plugin}</span>
        <span className="ml-auto flex items-center gap-3">
          <span className="text-xs text-fg-muted">
            {duration(step.duration_seconds)}
          </span>
          <StatusBadge status={step.status} />
          <span className="text-fg-subtle text-xs">{open ? '▲' : '▼'}</span>
        </span>
      </button>

      {open && (
        <div className="border-t border-border px-4 py-3 space-y-3 text-xs">
          {step.error && (
            <div className="rounded px-2 py-1.5 bg-danger-subtle text-danger font-mono whitespace-pre-wrap">
              {step.error}
            </div>
          )}
          <div>
            <h3 className="font-medium text-fg-muted mb-1">Inputs</h3>
            {hasInputs ? (
              <pre className="font-mono text-fg whitespace-pre-wrap break-words bg-canvas-subtle rounded p-2">
                {JSON.stringify(step.inputs, null, 2)}
              </pre>
            ) : (
              <p className="text-fg-muted">None</p>
            )}
          </div>
          <div>
            <h3 className="font-medium text-fg-muted mb-1">Outputs</h3>
            {hasOutputs ? (
              <pre className="font-mono text-fg whitespace-pre-wrap break-words bg-canvas-subtle rounded p-2">
                {JSON.stringify(step.outputs, null, 2)}
              </pre>
            ) : (
              <p className="text-fg-muted">
                {step.status === 'skipped' ? "Didn't run" : 'None'}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
