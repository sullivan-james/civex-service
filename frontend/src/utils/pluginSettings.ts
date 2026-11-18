import type { ConfigProperty, PluginInfo, PluginIOSpec } from '../api/plugins'
import { configType } from '../api/plugins'
import { INPUT_SOURCE, type DraftInput, type DraftStep } from './workflowModel'

/**
 * What the builder needs to draw a step's form, read from what its plugin
 * declares: each setting from the `Config` JSON schema (its `title`,
 * `description`, type, default and `x-civex` hint, see
 * `civex/plugins/hints.py`), and which earlier output can feed each input.
 * Nothing here knows any particular plugin.
 */

export interface SettingHint {
  kind?:
    | 'field'
    | 'schema'
    | 'collection'
    | 'record'
    | 'pattern'
    | 'date_format'
    | 'choice'
  of?: string
  dtypes?: string[]
  on?: string
  date_format?: string
  read_as?: string
  keys?: boolean
  pattern?: string
  choices?: { value: string; label: string }[]
  advanced?: boolean
}

export interface Setting {
  key: string
  title: string
  description: string
  /** 'string' | 'integer' | 'number' | 'boolean' | 'array' | 'object' | 'any' */
  type: string
  required: boolean
  default: unknown
  hint: SettingHint
}

type WithHint = ConfigProperty & { title?: string; 'x-civex'?: SettingHint }

/** "key_field" -> "Key field", for a setting with no title of its own. */
function titleOf(key: string): string {
  const words = key.replace(/_/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function pydanticTitle(key: string): string {
  return key
    .split('_')
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

export function settingsOf(plugin: PluginInfo | undefined): Setting[] {
  const schema = plugin?.config_schema
  const required = new Set(schema?.required ?? [])
  return Object.entries(schema?.properties ?? {}).map(([key, raw]) => {
    const prop = raw as WithHint
    const type = configType(prop).split(' | ')[0]
    return {
      key,
      // pydantic titles a setting it wasn't given one for "Key Field"; that
      // reads better as "Key field".
      title:
        prop.title && prop.title !== pydanticTitle(key)
          ? prop.title
          : titleOf(key),
      description: prop.description ?? '',
      type,
      required: required.has(key),
      default: prop.default,
      hint: prop['x-civex'] ?? {},
    }
  })
}

/** A step's settings that are blank but must be given. */
export function missingSettings(
  step: DraftStep,
  plugin: PluginInfo | undefined,
) {
  return settingsOf(plugin).filter((s) => {
    if (!s.required) return false
    const v = step.config[s.key]
    return v === undefined || v === null || v === ''
  })
}

export interface Source {
  /** What goes in the YAML: "step_id.output" or "__input__.name". */
  ref: string
  /** "the file from step 1, Read a file" */
  label: string
  type: string
}

function fits(want: string, have: string): boolean {
  return want === 'any' || have === 'any' || want === have
}

/** Everything that can feed input `spec` of the step at `index`: what the
 * workflow asks for when run, then each earlier step's outputs, nearest
 * first. Those of a fitting type come first (`fitting`); the rest are still
 * offered, since the server checks names, not types. */
export function sourcesFor(
  spec: PluginIOSpec,
  index: number,
  steps: DraftStep[],
  inputs: DraftInput[],
  plugins: PluginInfo[],
): { fitting: Source[]; others: Source[] } {
  const all: Source[] = []
  for (const input of inputs) {
    all.push({
      ref: `${INPUT_SOURCE}.${input.key}`,
      label:
        input.type === 'files'
          ? `The files given when it is run${input.label ? ` (${input.label})` : ''}`
          : `The value given when it is run${input.label ? ` (${input.label})` : ''}`,
      type: input.type === 'files' ? 'files' : 'any',
    })
  }
  for (let i = index - 1; i >= 0; i--) {
    const step = steps[i]
    const plugin = plugins.find((p) => p.id === step.plugin)
    for (const out of plugin?.outputs ?? []) {
      all.push({
        ref: `${step.id}.${out.name}`,
        label: `${outputWords(out)} from step ${i + 1}${plugin ? `, ${plugin.name}` : ''}`,
        type: out.type,
      })
    }
  }
  return {
    fitting: all.filter((s) => fits(spec.type, s.type)),
    others: all.filter((s) => !fits(spec.type, s.type)),
  }
}

/** An output said the way a person would: its description's first clause,
 * else its name. */
function outputWords(out: PluginIOSpec): string {
  const first = out.description?.split(/[.;(]/)[0]?.trim()
  if (first && first.length <= 48) return first.replace(/^The /, 'The ')
  return out.name.replace(/_/g, ' ')
}

/** The step with every empty input that has exactly one fitting source
 * filled with it: what a person would pick anyway. */
export function autoWire(
  step: DraftStep,
  index: number,
  steps: DraftStep[],
  inputs: DraftInput[],
  plugins: PluginInfo[],
): DraftStep {
  const plugin = plugins.find((p) => p.id === step.plugin)
  let changed = false
  const next = { ...step.inputs }
  for (const spec of plugin?.inputs ?? []) {
    if (next[spec.name]) continue
    const { fitting } = sourcesFor(spec, index, steps, inputs, plugins)
    if (fitting.length === 1) {
      next[spec.name] = fitting[0].ref
      changed = true
    }
  }
  return changed ? { ...step, inputs: next } : step
}

/** Inputs that name a step that doesn't come before this one any more. */
export function brokenInputs(
  step: DraftStep,
  index: number,
  steps: DraftStep[],
) {
  const before = new Set(steps.slice(0, index).map((s) => s.id))
  return Object.entries(step.inputs).filter(([, ref]) => {
    const source = ref.split('.')[0]
    return source !== INPUT_SOURCE && !before.has(source)
  })
}
