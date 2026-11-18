import { useWorkflow } from '../../hooks/useWorkflows'
import { useSchemas } from '../../hooks/useSchemas'
import type { PluginInfo } from '../../api/plugins'
import type { WorkflowDetail } from '../../api/workflows'
import type { Schema } from '../../api/schemas'
import { displayLabel } from '../../utils/naming'
import { fieldsWithInherited } from '../../utils/schemaFields'
import type { DraftInput, DraftStep } from '../../utils/workflowModel'
import { Badge, Card } from '../ui'
import { StepSays } from './builder/StepSays'

function kindLabel(schemas: Schema[], name: string): string {
  const s = schemas.find((x) => x.name === name)
  return s ? displayLabel(s.name, s.label) : name
}

/** When it runs, in words: what starts it, or that only a person does. */
function whenItRuns(detail: WorkflowDetail, schemas: Schema[]): string[] {
  const t = detail.triggers ?? {}
  const out: string[] = []
  if (t.record_created)
    out.push(
      `When a ${kindLabel(schemas, t.record_created.schema_name)} is added`,
    )
  const updated = t.record_updated
  if (updated) {
    const kind = kindLabel(schemas, updated.schema_name)
    const schema = schemas.find((s) => s.name === updated.schema_name)
    const fields = (updated.fields ?? []).map((name) => {
      const f = schema
        ? fieldsWithInherited(schema, schemas, false).find(
            (x) => x.name === name,
          )
        : undefined
      return f?.label ?? name
    })
    out.push(
      fields.length
        ? `When the ${fields.join(' or ')} of a ${kind} changes`
        : `When a ${kind} changes`,
    )
  }
  const by = detail.record_schema
    ? `when someone starts it on a ${kindLabel(schemas, detail.record_schema)}`
    : 'when someone starts it'
  out.push(out.length ? `Or ${by}` : by.charAt(0).toUpperCase() + by.slice(1))
  return out
}

/** A workflow in words: when it runs, what it asks for and what each step
 * does, the way the builder says it. The details are in the editor. */
export function WorkflowSummary({
  stem,
  plugins,
}: {
  stem: string
  plugins: PluginInfo[]
}) {
  const { data: detail, isLoading } = useWorkflow(stem)
  const { data: schemas = [] } = useSchemas()
  if (isLoading || !detail)
    return <p className="text-sm text-fg-muted">Loading…</p>

  const inputs: DraftInput[] = Object.entries(detail.inputs ?? {}).map(
    ([key, i]) => ({
      key,
      type: i.type === 'files' ? 'files' : 'value',
      label: i.label ?? '',
    }),
  )
  const steps: DraftStep[] = (detail.step_list ?? []).map((s) => ({
    ...s,
    condition: s.condition ?? '',
  }))
  const ctx = {
    schema: detail.record_schema ?? '',
    config: {},
    settings: [],
    schemas,
    collections: [],
    takesFiles: inputs.some((i) => i.type === 'files'),
  }

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      {detail.description && (
        <p className="text-sm text-fg">{detail.description}</p>
      )}
      <Card title="When it runs">
        <ul className="space-y-1 text-sm">
          {whenItRuns(detail, schemas).map((line) => (
            <li key={line}>{line}.</li>
          ))}
          {inputs.length > 0 && (
            <li className="text-fg-muted">
              It asks for{' '}
              {inputs
                .map((i) => i.label || (i.type === 'files' ? 'files' : i.key))
                .join(', ')}{' '}
              each time.
            </li>
          )}
        </ul>
      </Card>
      <Card title="What it does">
        <ol className="space-y-3">
          {steps.map((step, i) => {
            const plugin = plugins.find((p) => p.id === step.plugin)
            return (
              <li key={step.id} className="flex gap-3">
                <span className="self-start">
                  <Badge variant="accent">{i + 1}</Badge>
                </span>
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="text-sm font-medium">
                    {plugin?.name ?? step.plugin}
                    {step.condition && (
                      <span className="ml-2 text-xs font-normal text-fg-muted">
                        only in some cases
                      </span>
                    )}
                  </p>
                  <StepSays
                    step={step}
                    index={i}
                    steps={steps}
                    inputs={inputs}
                    plugins={plugins}
                    ctx={ctx}
                  />
                </div>
              </li>
            )
          })}
        </ol>
      </Card>
    </div>
  )
}
