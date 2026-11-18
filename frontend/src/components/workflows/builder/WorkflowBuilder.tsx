import type { PluginInfo } from '../../../api/plugins'
import type { Schema } from '../../../api/schemas'
import type { Collection } from '../../../api/collections'
import {
  Button,
  Card,
  CheckRow,
  Field,
  FormGrid,
  Input,
  MultiPick,
  Select,
  Textarea,
} from '../../ui'
import { Plus } from '../../ui/icons'
import { autoWire, settingsOf } from '../../../utils/pluginSettings'
import { fieldsWithInherited } from '../../../utils/schemaFields'
import { displayLabel } from '../../../utils/naming'
import {
  newStepId,
  type DraftStep,
  type WorkflowDraft,
} from '../../../utils/workflowModel'
import { StepCard } from './StepCard'

interface Props {
  draft: WorkflowDraft
  onChange: (draft: WorkflowDraft) => void
  plugins: PluginInfo[]
  schemas: Schema[]
  collections: Collection[]
  /** What the server said is wrong, by step id ('' for the workflow). */
  errors: Map<string, string[]>
  showMissing: boolean
}

/** `steps` with every reference to step `from` pointing at `to` instead. */
function renameStep(steps: DraftStep[], from: string, to: string): DraftStep[] {
  if (from === to) return steps
  const re = new RegExp(`(^|[^\\w-])${from.replace(/[-]/g, '\\-')}\\.`, 'g')
  return steps.map((s) => ({
    ...s,
    id: s.id === from ? to : s.id,
    inputs: Object.fromEntries(
      Object.entries(s.inputs).map(([k, ref]) => [
        k,
        ref.startsWith(`${from}.`) ? `${to}${ref.slice(from.length)}` : ref,
      ]),
    ),
    condition: s.condition.replace(re, `$1${to}.`),
  }))
}

/** Each step from `start` on, with inputs that have one obvious source
 * filled in. */
function wireFrom(
  steps: DraftStep[],
  start: number,
  draft: WorkflowDraft,
  plugins: PluginInfo[],
): DraftStep[] {
  const out = [...steps]
  for (let i = start; i < out.length; i++) {
    out[i] = autoWire(out[i], i, out, draft.inputs, plugins)
  }
  return out
}

/** A step id made by the builder (as opposed to one somebody chose). */
function madeUp(id: string): boolean {
  return /^step(_\d+)?$/.test(id)
}

export function WorkflowBuilder({
  draft,
  onChange,
  plugins,
  schemas,
  collections,
  errors,
  showMissing,
}: Props) {
  const set = (patch: Partial<WorkflowDraft>) =>
    onChange({ ...draft, ...patch })
  const schema = schemas.find((s) => s.name === draft.schema)
  const kind = schema ? displayLabel(schema.name, schema.label) : 'record'
  const fieldOptions = schema
    ? fieldsWithInherited(schema, schemas, false).map((f) => ({
        value: f.name,
        label: f.label,
      }))
    : []
  const writes = draft.steps.some((s) =>
    plugins
      .find((p) => p.id === s.plugin)
      ?.capabilities.some(
        (c) => c === 'update_record' || c === 'create_record',
      ),
  )
  const filesInput = draft.inputs.find((i) => i.type === 'files')

  function setSteps(steps: DraftStep[]) {
    set({ steps })
  }

  function changePlugin(index: number, pluginId: string) {
    const plugin = plugins.find((p) => p.id === pluginId)
    const old = draft.steps[index]
    const keys = new Set(settingsOf(plugin).map((s) => s.key))
    const ins = new Set((plugin?.inputs ?? []).map((i) => i.name))
    let steps = draft.steps.map((s, i) =>
      i === index
        ? {
            ...s,
            plugin: pluginId,
            config: Object.fromEntries(
              Object.entries(s.config).filter(([k]) => keys.has(k)),
            ),
            inputs: Object.fromEntries(
              Object.entries(s.inputs).filter(([k]) => ins.has(k)),
            ),
          }
        : s,
    )
    if (plugin && madeUp(old.id)) {
      steps = renameStep(
        steps,
        old.id,
        newStepId(
          plugin.name,
          steps.filter((_, i) => i !== index).map((s) => s.id),
        ),
      )
    }
    setSteps(wireFrom(steps, index, draft, plugins))
  }

  function move(index: number, by: -1 | 1) {
    const steps = [...draft.steps]
    const [step] = steps.splice(index, 1)
    steps.splice(index + by, 0, step)
    setSteps(steps)
  }

  function addStep() {
    const id = newStepId(
      'step',
      draft.steps.map((s) => s.id),
    )
    setSteps([
      ...draft.steps,
      { id, plugin: '', config: {}, inputs: {}, condition: '' },
    ])
  }

  const general = errors.get('') ?? []

  return (
    <div className="flex flex-col gap-4">
      <Card title="About">
        <FormGrid>
          <Field label="Name" span={6} required>
            <Input
              value={draft.name}
              onChange={(e) => set({ name: e.target.value })}
              placeholder="Fill the date from the recording’s name"
            />
          </Field>
          <Field label="What it’s for" span={12}>
            <Textarea
              rows={2}
              value={draft.description}
              onChange={(e) => set({ description: e.target.value })}
            />
          </Field>
        </FormGrid>
      </Card>

      <Card title="When it runs">
        <div className="space-y-3">
          <Field
            label="Runs on"
            info="The kind of record it works on: the one it starts from."
            error={
              showMissing && !draft.schema
                ? 'Choose the kind of record it runs on.'
                : undefined
            }
          >
            <Select
              value={draft.schema}
              onChange={(e) => set({ schema: e.target.value, watchFields: [] })}
            >
              <option value="">— choose a kind of record —</option>
              {draft.schema && !schema && (
                <option value={draft.schema}>{draft.schema}</option>
              )}
              {schemas.map((s) => (
                <option key={s.id} value={s.name}>
                  {displayLabel(s.name, s.label)}
                </option>
              ))}
            </Select>
          </Field>
          <p className="text-sm text-fg-muted">
            You can always start it yourself from a {kind}’s page. It can also
            start by itself:
          </p>
          <CheckRow
            checked={draft.onCreated}
            disabled={!draft.schema}
            onChange={(on) => set({ onCreated: on })}
            title={`When a ${kind} is added`}
          />
          <CheckRow
            checked={draft.onUpdated}
            disabled={!draft.schema}
            onChange={(on) => set({ onUpdated: on })}
            title={`When a ${kind} changes`}
          >
            <div className="space-y-2">
              <MultiPick
                label="Fields to watch"
                options={fieldOptions}
                value={draft.watchFields}
                onChange={(watchFields) => set({ watchFields })}
              />
              {writes && draft.watchFields.length === 0 && (
                <p className="text-xs text-attention">
                  It changes records itself, so watching every field can start
                  it again by its own save. Choose the fields it should react
                  to.
                </p>
              )}
            </div>
          </CheckRow>
          <CheckRow
            checked={!!filesInput}
            onChange={(on) =>
              set({
                inputs: on
                  ? [
                      ...draft.inputs,
                      { key: 'files', type: 'files', label: 'Files' },
                    ]
                  : draft.inputs.filter((i) => i.type !== 'files'),
              })
            }
            title="Asks for files when someone starts it"
            description="For a batch of files to sort onto records: they are chosen each time it runs."
          >
            {filesInput && (
              <Field label="What to call them">
                <Input
                  size="sm"
                  value={filesInput.label}
                  onChange={(e) =>
                    set({
                      inputs: draft.inputs.map((i) =>
                        i === filesInput ? { ...i, label: e.target.value } : i,
                      ),
                    })
                  }
                />
              </Field>
            )}
          </CheckRow>
          {draft.onCreated || draft.onUpdated ? (
            <p className="text-xs text-fg-muted">
              {draft.enabled
                ? 'It is on: these start it.'
                : 'It is off: nothing starts it by itself until you turn it on, after trying it.'}
            </p>
          ) : null}
        </div>
      </Card>

      <section className="flex flex-col gap-3" aria-label="Steps">
        <h2 className="text-sm font-semibold text-fg">Then, in order</h2>
        {draft.steps.length === 0 && (
          <p className="text-sm text-fg-muted">
            No steps yet. Each step does one thing: read a file, take a value
            from a name, set a field, make records.
          </p>
        )}
        {draft.steps.map((step, i) => (
          <StepCard
            key={`${i}:${step.id}`}
            step={step}
            index={i}
            steps={draft.steps}
            inputs={draft.inputs}
            plugins={plugins}
            ctx={{
              schema: draft.schema,
              schemas,
              collections,
              takesFiles: !!filesInput,
            }}
            errors={errors.get(step.id) ?? []}
            showMissing={showMissing}
            onChange={(next) =>
              setSteps(draft.steps.map((s, j) => (j === i ? next : s)))
            }
            onChangePlugin={(pid) => changePlugin(i, pid)}
            onMove={(by) => move(i, by)}
            onRemove={() => setSteps(draft.steps.filter((_, j) => j !== i))}
          />
        ))}
        <div>
          <Button onClick={addStep}>
            <Plus size={14} aria-hidden /> Add a step
          </Button>
        </div>
      </section>

      {general.length > 0 && (
        <ul className="list-disc rounded-md border border-danger-subtle-border bg-danger-subtle p-3 pl-7 text-xs text-danger">
          {general.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
