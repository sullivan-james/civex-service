import { useState } from 'react'
import { type StepExecution } from '../../api/workflows'
import { Badge } from '../ui'
import {
  Check,
  XCircle,
  SkipForward,
  ChevronUp,
  ChevronDown,
} from '../ui/icons'

function StatusBadge({ status }: { status: StepExecution['status'] }) {
  switch (status) {
    case 'success':
      return (
        <Badge variant="success" className="gap-1">
          <Check size={12} /> success
        </Badge>
      )
    case 'failed':
      return (
        <Badge variant="danger" className="gap-1">
          <XCircle size={12} /> failed
        </Badge>
      )
    default:
      return (
        <Badge variant="default" className="gap-1">
          <SkipForward size={12} /> skipped
        </Badge>
      )
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
    <div className="rounded-md border border-[#d0d7de] bg-white overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-[#f6f8fa] transition-colors"
      >
        <span className="font-mono text-sm text-[#1f2328]">{step.step_id}</span>
        <span className="text-xs text-[#656d76] font-mono">{step.plugin}</span>
        <span className="ml-auto flex items-center gap-3">
          <span className="text-xs text-[#656d76]">
            {duration(step.duration_seconds)}
          </span>
          <StatusBadge status={step.status} />
          <span className="text-[#adbac7]">
            {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </span>
        </span>
      </button>

      {open && (
        <div className="border-t border-[#d0d7de] px-4 py-3 space-y-3 text-xs">
          {step.error && (
            <div className="rounded px-2 py-1.5 bg-[#ffebe9] text-[#d1242f] font-mono whitespace-pre-wrap">
              {step.error}
            </div>
          )}
          <div>
            <h3 className="font-medium text-[#656d76] mb-1">Inputs</h3>
            {hasInputs ? (
              <pre className="font-mono text-[#1f2328] whitespace-pre-wrap break-words bg-[#f6f8fa] rounded p-2">
                {JSON.stringify(step.inputs, null, 2)}
              </pre>
            ) : (
              <p className="text-[#656d76]">None</p>
            )}
          </div>
          <div>
            <h3 className="font-medium text-[#656d76] mb-1">Outputs</h3>
            {hasOutputs ? (
              <pre className="font-mono text-[#1f2328] whitespace-pre-wrap break-words bg-[#f6f8fa] rounded p-2">
                {JSON.stringify(step.outputs, null, 2)}
              </pre>
            ) : (
              <p className="text-[#656d76]">
                {step.status === 'skipped' ? "Didn't run" : 'None'}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
