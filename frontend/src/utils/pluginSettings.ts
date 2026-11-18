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
  /** Where it comes from and what it is: "Step 1: the file's contents". */
  label: string
  /** Just what it is, said in a sentence: "the file's contents". */
  words: string
  /** Where it comes from: "Step 1, Read a file" or "Given when it runs". */
  origin: string
  type: string
}

const lower = (t: string) => t.charAt(0).toLowerCase() + t.slice(1)

/** An input as a person would name it: its description's first clause
 * ("The files to put on records" -> "Files to put on records"), else its
 * name. */
export function inputLabel(spec: PluginIOSpec): string {
  const first = spec.description?.split(/[.;:(]/)[0]?.trim()
  if (first && first.length <= 48) {
    const t = first.replace(/^The /, '')
    return t.charAt(0).toUpperCase() + t.slice(1)
  }
  return titleOf(spec.name)
}

/** The sentence a plugin gives for what a step does, with `{setting}` and
 * `{input}` blanks; null when it gives none. */
export function sentenceOf(plugin: PluginInfo | undefined): string | null {
  const says = (
    plugin?.config_schema as { 'x-civex-says'?: unknown } | undefined
  )?.['x-civex-says']
  return typeof says === 'string' && says ? says : null
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
    const what = input.type === 'files' ? 'the files' : 'the value'
    // "(Files)" says nothing beside "the files".
    const named =
      input.label && input.label.toLowerCase() !== what.slice(4)
        ? ` (${input.label})`
        : ''
    const words = `${what} given when it is run${named}`
    all.push({
      ref: `${INPUT_SOURCE}.${input.key}`,
      label: words.charAt(0).toUpperCase() + words.slice(1),
      words,
      origin: 'Given when it runs',
      type: input.type === 'files' ? 'files' : 'any',
    })
  }
  for (let i = index - 1; i >= 0; i--) {
    const step = steps[i]
    const plugin = plugins.find((p) => p.id === step.plugin)
    for (const out of plugin?.outputs ?? []) {
      const words = lower(outputWords(out))
      all.push({
        ref: `${step.id}.${out.name}`,
        label: `Step ${i + 1}: ${words}`,
        words,
        origin: `Step ${i + 1}${plugin ? `, ${plugin.name}` : ''}`,
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
  const first = out.description?.split(/[.;(:]/)[0]?.trim()
  if (first && first.length <= 48) return first
  return `its ${out.name.replace(/_/g, ' ')}`
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
