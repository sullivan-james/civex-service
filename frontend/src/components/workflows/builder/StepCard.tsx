import type { PluginInfo, PluginIOSpec } from '../../../api/plugins'
import {
  Badge,
  Card,
  CheckRow,
  Disclosure,
  Field,
  IconButton,
  Input,
  Select,
} from '../../ui'
import { ArrowDown, ArrowUp, Trash2 } from '../../ui/icons'
import {
  brokenInputs,
  inputLabel,
  missingSettings,
  settingsOf,
  sourcesFor,
} from '../../../utils/pluginSettings'
import {
  CONDITION_OPS,
  readCondition,
  writeCondition,
  type ConditionOp,
} from '../../../utils/stepCondition'
import {
  INPUT_SOURCE,
  type DraftInput,
  type DraftStep,
} from '../../../utils/workflowModel'
import { SettingControl, type SettingContext } from './SettingControl'
import { StepSays } from './StepSays'

/** The groups of built-in steps, in the order they are offered. */
const CATEGORY_LABELS: Record<string, string> = {
  'bring-in': 'Bring in',
  'work-out': 'Work out',
  save: 'Save',
}
const GROUP_ORDER = [...Object.values(CATEGORY_LABELS), 'Other', 'Your plugins']

/** The actions to choose from, grouped by what they do, each by its name. */
export function ActionSelect({
  value,
  plugins,
  onChange,
  id,
}: {
  value: string
  plugins: PluginInfo[]
  onChange: (pluginId: string) => void
  id?: string
}) {
  const groups = new Map<string, PluginInfo[]>()
  const ordered = [...plugins].sort(
    (a, b) =>
      Number(b.builtin) - Number(a.builtin) || a.name.localeCompare(b.name),
  )
  for (const p of ordered) {
    const group = p.builtin
      ? (CATEGORY_LABELS[p.category] ?? 'Other')
      : 'Your plugins'
    groups.set(group, [...(groups.get(group) ?? []), p])
  }
  return (
    <Select
      size="sm"
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">— choose what this step does —</option>
      {value && !plugins.some((p) => p.id === value) && (
        <option value={value}>{value} (not installed)</option>
      )}
      {[...groups]
        .sort((a, b) => GROUP_ORDER.indexOf(a[0]) - GROUP_ORDER.indexOf(b[0]))
        .map(([group, items]) => (
          <optgroup key={group} label={group}>
            {items.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </optgroup>
        ))}
    </Select>
  )
}

interface Props {
  step: DraftStep
  index: number
  steps: DraftStep[]
  inputs: DraftInput[]
  plugins: PluginInfo[]
  ctx: Omit<SettingContext, 'config' | 'settings'>
  errors: string[]
  onChange: (step: DraftStep) => void
  onChangePlugin: (pluginId: string) => void
  onMove: (by: -1 | 1) => void
  onRemove: () => void
  /** Whether the settings left blank are shown as missing yet. */
  showMissing: boolean
}

function ConditionEditor({
  step,
  index,
  steps,
  inputs,
  plugins,
  onChange,
}: Pick<
  Props,
  'step' | 'index' | 'steps' | 'inputs' | 'plugins' | 'onChange'
>) {
  const parsed = readCondition(step.condition)
  const on = step.condition.trim() !== ''
  const { fitting } = sourcesFor(
    { name: '', type: 'any', required: false, description: '' },
    index,
    steps,
    inputs,
    plugins,
  )
  // An `if:` reads `step.output`, so a step id with a dash can't be named.
  const sources = fitting.filter((s) => /^[A-Za-z_]\w*\./.test(s.ref))
  const set = (ref: string, op: ConditionOp, value: string) =>
    onChange({ ...step, condition: writeCondition({ ref, op, value }) })
  return (
    <CheckRow
      compact
      checked={on}
      title="Only run this step when…"
      onChange={(checked) => {
        if (!checked) onChange({ ...step, condition: '' })
        else if (sources[0]) set(sources[0].ref, 'set', '')
      }}
      disabled={!on && sources.length === 0}
      description={
        !on && sources.length === 0
          ? 'A step can only depend on what an earlier step gives.'
          : undefined
      }
    >
      {on && parsed ? (
        <div className="flex flex-wrap items-center gap-2">
          <Select
            size="sm"
            aria-label="Value tested"
            value={parsed.ref}
            onChange={(e) => set(e.target.value, parsed.op, parsed.value)}
          >
            {!sources.some((s) => s.ref === parsed.ref) && (
              <option value={parsed.ref}>{parsed.ref}</option>
            )}
            {sources.map((s) => (
              <option key={s.ref} value={s.ref}>
                {s.label}
              </option>
            ))}
          </Select>
          <Select
            size="sm"
            aria-label="Test"
            value={parsed.op}
            onChange={(e) =>
              set(parsed.ref, e.target.value as ConditionOp, parsed.value)
            }
          >
            {CONDITION_OPS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
          {parsed.op !== 'set' && parsed.op !== 'unset' && (
            <Input
              size="sm"
              aria-label="Compared with"
              value={parsed.value}
              onChange={(e) => set(parsed.ref, parsed.op, e.target.value)}
            />
          )}
        </div>
      ) : on ? (
        <Input
          size="sm"
          aria-label="Condition"
          className="font-mono"
          value={step.condition}
          onChange={(e) => onChange({ ...step, condition: e.target.value })}
        />
      ) : null}
    </CheckRow>
  )
}

const lowerFirst = (t: string) => t.charAt(0).toLowerCase() + t.slice(1)

/** Where an input of the step comes from. With one thing that can give it,
 * already chosen, that is said in words; a list only when there is a choice. */
function InputSource({
  spec,
  step,
  index,
  steps,
  inputs,
  plugins,
  broken,
  showMissing,
  onChange,
}: {
  spec: PluginIOSpec
  step: DraftStep
  index: number
  steps: DraftStep[]
  inputs: DraftInput[]
  plugins: PluginInfo[]
  broken: boolean
  showMissing: boolean
  onChange: (ref: string) => void
}) {
  const { fitting, others } = sourcesFor(spec, index, steps, inputs, plugins)
  const current = step.inputs[spec.name] ?? ''
  const all = [...fitting, ...others]
  const chosen = all.find((s) => s.ref === current)
  const label = inputLabel(spec)
  const error = broken
    ? 'This came from a step that is now later or gone: choose again.'
    : showMissing && spec.required && !current
      ? 'Choose where this comes from.'
      : undefined
  if (all.length === 0) {
    return (
      <Field label={label} info={spec.description || undefined} error={error}>
        <p className="text-sm text-fg-muted">
          Nothing before this step gives this. Add a step above it that does, or
          have it ask for files when it is started.
        </p>
      </Field>
    )
  }
  if (chosen && fitting.length === 1 && fitting[0] === chosen) {
    return (
      <Field label={label} info={spec.description || undefined}>
        <p className="text-sm">
          {chosen.ref.startsWith(`${INPUT_SOURCE}.`) ? (
            chosen.label
          ) : (
            <>
              <span className="text-fg-muted">
                From {lowerFirst(chosen.origin)}:
              </span>{' '}
              {chosen.words}
            </>
          )}
        </p>
      </Field>
    )
  }
  return (
    <Field
      label={label}
      info={spec.description || undefined}
      required={spec.required}
      error={error}
    >
      <Select
        size="sm"
        value={current}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">— where does it come from? —</option>
        {current && !chosen && <option value={current}>{current}</option>}
        {fitting.map((s) => (
          <option key={s.ref} value={s.ref}>
            {s.label}
          </option>
        ))}
        {others.length > 0 && (
          <optgroup label="Other values (may not fit)">
            {others.map((s) => (
              <option key={s.ref} value={s.ref}>
                {s.label}
              </option>
            ))}
          </optgroup>
        )}
      </Select>
    </Field>
  )
}

export function StepCard(props: Props) {
  const {
    step,
    index,
    steps,
    inputs,
    plugins,
    ctx,
    errors,
    onChange,
    onChangePlugin,
    onMove,
    onRemove,
    showMissing,
  } = props
  const plugin = plugins.find((p) => p.id === step.plugin)
  const settings = settingsOf(plugin)
  const missing = new Set(missingSettings(step, plugin).map((s) => s.key))
  const broken = new Set(brokenInputs(step, index, steps).map(([k]) => k))
  const settingCtx: SettingContext = { ...ctx, config: step.config, settings }
  // Several settings change in one update, or the last would undo the others.
  const setSome = (values: Record<string, unknown>) =>
    onChange({ ...step, config: { ...step.config, ...values } })
  const setConfig = (key: string, value: unknown) => setSome({ [key]: value })
  // A setting that depends on another (the folder, once "A folder" is chosen)
  // is shown only then.
  const shown = settings.filter((s) => {
    const when = s.hint.when
    if (!when) return true
    const governing = settings.find((o) => o.key === when.setting)
    const current = step.config[when.setting] ?? governing?.default
    return when.is.includes(String(current ?? ''))
  })
  const basic = shown.filter((s) => !s.hint.advanced)
  const advanced = shown.filter((s) => s.hint.advanced)
  const control = (s: (typeof settings)[number]) => (
    <SettingControl
      key={s.key}
      setting={s}
      value={step.config[s.key]}
      onChange={(v) => setConfig(s.key, v)}
      onChangeSome={setSome}
      ctx={settingCtx}
      missing={showMissing && missing.has(s.key)}
    />
  )

  return (
    <Card
      variant={errors.length ? 'danger' : 'static'}
      title={
        <span className="flex items-center gap-2">
          <Badge variant="accent">{index + 1}</Badge>
          {plugin?.name ?? (step.plugin || 'New step')}
        </span>
      }
      action={
        <div className="flex items-center gap-1">
          <IconButton
            icon={ArrowUp}
            aria-label="Move up"
            disabled={index === 0}
            onClick={() => onMove(-1)}
          />
          <IconButton
            icon={ArrowDown}
            aria-label="Move down"
            disabled={index === steps.length - 1}
            onClick={() => onMove(1)}
          />
          <IconButton
            icon={Trash2}
            aria-label="Remove step"
            onClick={onRemove}
          />
        </div>
      }
    >
      <div className="space-y-3" data-step={step.id}>
        <StepSays
          step={step}
          index={index}
          steps={steps}
          inputs={inputs}
          plugins={plugins}
          ctx={settingCtx}
        />
        <Field
          label="What it does"
          info={plugin?.description || undefined}
          error={
            showMissing && !step.plugin
              ? 'Choose what this step does.'
              : undefined
          }
        >
          <ActionSelect
            value={step.plugin}
            plugins={plugins}
            onChange={onChangePlugin}
          />
        </Field>

        {(plugin?.inputs ?? []).map((spec) => (
          <InputSource
            key={spec.name}
            spec={spec}
            step={step}
            index={index}
            steps={steps}
            inputs={inputs}
            plugins={plugins}
            broken={broken.has(spec.name)}
            showMissing={showMissing}
            onChange={(ref) =>
              onChange({
                ...step,
                inputs: { ...step.inputs, [spec.name]: ref },
              })
            }
          />
        ))}

        {basic.map(control)}
        {advanced.length > 0 && (
          <Disclosure summary="More settings">
            <div className="space-y-3 p-3">{advanced.map(control)}</div>
          </Disclosure>
        )}

        <ConditionEditor
          step={step}
          index={index}
          steps={steps}
          inputs={inputs}
          plugins={plugins}
          onChange={onChange}
        />

        {errors.length > 0 && (
          <ul className="list-disc pl-5 text-xs text-danger">
            {errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  )
}
