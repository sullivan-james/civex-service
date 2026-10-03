import { type StepExecution } from '../../api/workflows'
import { type PluginInfo } from '../../api/plugins'
import { Badge, Disclosure } from '../ui'
import { Check, XCircle, SkipForward } from '../ui/icons'
import { pluginDisplayName, stepStory } from '../../utils/runNarrative'
import StepValueDisplay from './StepValueDisplay'

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

function ValueList({ values }: { values: Record<string, unknown> }) {
  const entries = Object.entries(values)
  if (entries.length === 0) return <p className="text-fg-muted">None</p>
  return (
    <div className="space-y-2">
      {entries.map(([key, value]) => (
        <div key={key}>
          <span className="font-mono text-fg-muted">{key}</span>
          <div className="mt-0.5">
            <StepValueDisplay value={value} />
          </div>
        </div>
      ))}
    </div>
  )
}

export default function StepExecutionCard({
  step,
  plugins,
}: {
  step: StepExecution
  plugins?: PluginInfo[]
}) {
  const hasInputs = step.inputs && Object.keys(step.inputs).length > 0
  const hasOutputs = step.outputs && Object.keys(step.outputs).length > 0

  return (
    <Disclosure
      defaultOpen={step.status === 'failed'}
      summary={
        <span className="flex flex-col gap-1">
          <span className="flex items-center gap-3">
            <span className="font-medium text-fg">
              {pluginDisplayName(step.plugin, plugins)}
            </span>
            <span className="ml-auto flex items-center gap-3">
              <span className="text-xs text-fg-muted">
                {duration(step.duration_seconds)}
              </span>
              <StatusBadge status={step.status} />
            </span>
          </span>
          <span className="text-xs text-fg-muted">{stepStory(step)}</span>
        </span>
      }
    >
      <div className="px-4 py-3 space-y-3 text-xs">
        {step.error && (
          <div className="rounded-md px-2 py-2 bg-danger-subtle text-danger font-mono whitespace-pre-wrap">
            {step.error}
          </div>
        )}
        <div className="flex items-center gap-2 text-fg-subtle">
          <span className="font-mono">{step.step_id}</span>
          <span aria-hidden>·</span>
          <span className="font-mono">{step.plugin}</span>
        </div>
        <div>
          <h3 className="font-medium text-fg-muted mb-1">Inputs</h3>
          {hasInputs ? (
            <ValueList values={step.inputs} />
          ) : (
            <p className="text-fg-muted">None</p>
          )}
        </div>
        <div>
          <h3 className="font-medium text-fg-muted mb-1">Outputs</h3>
          {hasOutputs ? (
            <ValueList values={step.outputs!} />
          ) : (
            <p className="text-fg-muted">
              {step.status === 'skipped' ? "Didn't run" : 'None'}
            </p>
          )}
        </div>
      </div>
    </Disclosure>
  )
}
