import {
  Badge,
  Button,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
} from '../ui'
import { FileCode } from '../ui/icons'
import { useWorkflow } from '../../hooks/useWorkflows'
import type { PluginInfo } from '../../api/plugins'
import type { Workflow, WorkflowStep } from '../../api/workflows'

interface WorkflowSummaryModalProps {
  workflow: Workflow
  plugins: PluginInfo[]
  onClose: () => void
}

function TriggerSummary({
  triggers,
}: {
  triggers: Record<
    string,
    { schema_name: string; fields: string[] | null }
  > | null
}) {
  if (!triggers || Object.keys(triggers).length === 0) {
    return <p className="text-sm text-fg-muted">Manual only</p>
  }
  return (
    <ul className="text-sm text-fg space-y-1">
      {triggers.record_created && (
        <li>
          Runs automatically when a{' '}
          <span className="font-mono text-fg">
            {triggers.record_created.schema_name}
          </span>{' '}
          record is created.
        </li>
      )}
      {triggers.record_updated && (
        <li>
          Runs automatically when a{' '}
          <span className="font-mono text-fg">
            {triggers.record_updated.schema_name}
          </span>{' '}
          record is updated
          {triggers.record_updated.fields
            ? ` and one of these fields changes: ${triggers.record_updated.fields.join(', ')}.`
            : '.'}
        </li>
      )}
    </ul>
  )
}

function StepCard({
  step,
  index,
  plugin,
}: {
  step: WorkflowStep
  index: number
  plugin: PluginInfo | undefined
}) {
  const configEntries = Object.entries(step.config)
  const inputEntries = Object.entries(step.inputs)

  return (
    <li className="border border-border rounded-md p-3">
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant="accent">{index + 1}</Badge>
        <span className="font-medium text-fg font-mono text-sm">{step.id}</span>
        <span className="text-fg-muted text-xs">·</span>
        <span className="font-mono text-xs text-fg-muted">{step.plugin}</span>
        {plugin?.name && (
          <span className="text-xs text-fg-muted">({plugin.name})</span>
        )}
      </div>

      {plugin?.description && (
        <p className="text-xs text-fg-muted mt-1">{plugin.description}</p>
      )}

      {step.condition && (
        <p className="text-xs text-fg-muted mt-2">
          Only runs if:{' '}
          <span className="font-mono text-fg">{step.condition}</span>
        </p>
      )}

      <div className="grid sm:grid-cols-3 gap-3 mt-3">
        <div>
          <h4 className="text-xs font-semibold text-fg mb-1">Config</h4>
          {configEntries.length === 0 ? (
            <p className="text-xs text-fg-muted">none</p>
          ) : (
            <ul className="text-xs space-y-0.5">
              {configEntries.map(([key, value]) => (
                <li key={key} className="font-mono">
                  <span className="text-fg">{key}</span>
                  <span className="text-fg-muted">
                    : {JSON.stringify(value)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h4 className="text-xs font-semibold text-fg mb-1">Inputs</h4>
          {inputEntries.length === 0 ? (
            <p className="text-xs text-fg-muted">none</p>
          ) : (
            <ul className="text-xs space-y-0.5">
              {inputEntries.map(([name, source]) => (
                <li key={name} className="font-mono">
                  <span className="text-fg">{name}</span>
                  <span className="text-fg-muted"> ← {source}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h4 className="text-xs font-semibold text-fg mb-1">Outputs</h4>
          {plugin?.outputs === null || plugin?.outputs === undefined ? (
            <p className="text-xs text-fg-muted italic">not declared</p>
          ) : plugin.outputs.length === 0 ? (
            <p className="text-xs text-fg-muted">none</p>
          ) : (
            <ul className="text-xs space-y-0.5">
              {plugin.outputs.map((o) => (
                <li key={o.name} className="font-mono">
                  <span className="text-fg">
                    {step.id}.{o.name}
                  </span>
                  <span className="text-fg-muted"> : {o.type}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </li>
  )
}

/** Readable view of a workflow — trigger, steps, their inputs and outputs —
 * so an automation can be understood without reading its YAML. "Edit as
 * YAML" is the explicit escape hatch into the WorkflowEditorPage, opened in
 * a new tab. */
export function WorkflowSummaryModal({
  workflow,
  plugins,
  onClose,
}: WorkflowSummaryModalProps) {
  const { data: detail, isLoading } = useWorkflow(workflow.stem)
  const pluginsById = new Map(plugins.map((p) => [p.id, p]))

  return (
    <Modal onClose={onClose} size="2xl" className="h-[90vh]">
      <ModalHeader onClose={onClose}>{workflow.name}</ModalHeader>

      <ModalBody className="flex flex-col gap-5">
        {isLoading || !detail ? (
          <div className="flex-1 flex items-center justify-center text-sm text-fg-muted">
            Loading…
          </div>
        ) : (
          <>
            {detail.description && (
              <p className="text-sm text-fg-muted">{detail.description}</p>
            )}

            <div>
              <h3 className="text-sm font-semibold text-fg mb-2">Trigger</h3>
              <TriggerSummary triggers={detail.triggers} />
            </div>

            {detail.inputs && Object.keys(detail.inputs).length > 0 && (
              <div>
                <h3 className="text-sm font-semibold text-fg mb-2">
                  Manual run inputs
                </h3>
                <ul className="text-sm space-y-1">
                  {Object.entries(detail.inputs).map(([name, input]) => (
                    <li key={name} className="font-mono text-fg">
                      {input.label ?? name}
                      <span className="text-fg-muted font-sans">
                        {' '}
                        — {input.type}
                        {input.description ? `, ${input.description}` : ''}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div>
              <h3 className="text-sm font-semibold text-fg mb-2">
                Steps ({(detail.step_list ?? []).length})
              </h3>
              <ul className="space-y-3">
                {(detail.step_list ?? []).map((step, i) => (
                  <StepCard
                    key={step.id}
                    step={step}
                    index={i}
                    plugin={pluginsById.get(step.plugin)}
                  />
                ))}
              </ul>
            </div>
          </>
        )}
      </ModalBody>

      <ModalFooter>
        <Button variant="default" onClick={onClose}>
          Close
        </Button>
        <Button
          to={`/workflows/${workflow.stem}/edit`}
          target="_blank"
          rel="opener"
        >
          <FileCode size={14} />
          Edit as YAML
        </Button>
      </ModalFooter>
    </Modal>
  )
}
