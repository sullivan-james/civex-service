import type { PluginInfo } from '../../../api/plugins'
import { fieldsWithInherited } from '../../../utils/schemaFields'
import { displayLabel } from '../../../utils/naming'
import { describePattern } from '../../../utils/patternFromExample'
import {
  sentenceOf,
  settingsOf,
  sourcesFor,
  type Setting,
} from '../../../utils/pluginSettings'
import type { DraftInput, DraftStep } from '../../../utils/workflowModel'
import type { SettingContext } from './SettingControl'

const blank = (v: unknown) => v === undefined || v === null || v === ''

/** A setting's value as it reads in a sentence: a field or kind of record by
 * its name, a choice by its words. Null while it isn't chosen. */
function settingWords(
  setting: Setting,
  value: unknown,
  ctx: SettingContext,
  config: Record<string, unknown>,
): string | null {
  const { hint } = setting
  const v = blank(value) ? setting.default : value
  if (hint.kind === 'collection')
    return blank(v) ? 'its own collection' : String(v)
  if (blank(v)) return null
  if (hint.kind === 'schema') {
    const s = ctx.schemas.find((x) => x.name === v)
    return s ? displayLabel(s.name, s.label) : String(v)
  }
  if (hint.kind === 'field') {
    const of = hint.of ? String(config[hint.of] ?? '') : ctx.schema
    const schema = ctx.schemas.find((x) => x.name === of)
    const field = schema
      ? fieldsWithInherited(schema, ctx.schemas, false).find(
          (f) => f.name === v,
        )
      : undefined
    return field?.label ?? String(v)
  }
  if (hint.kind === 'choice')
    return hint.choices?.find((c) => c.value === v)?.label ?? String(v)
  if (hint.kind === 'pattern') {
    const fmt = hint.date_format ? config[hint.date_format] : null
    if (!blank(fmt)) return `the date written ${String(fmt)}`
    return describePattern(String(v)) ?? 'the part its pattern takes'
  }
  if (Array.isArray(v)) return v.join(', ')
  if (typeof v === 'object') return 'the values given'
  return String(v)
}

/** What the step does, in the plugin's own sentence, filled in with what has
 * been chosen so far; blanks show as "…". Nothing when the plugin gives no
 * sentence. */
export function StepSays({
  step,
  index,
  steps,
  inputs,
  plugins,
  ctx,
}: {
  step: DraftStep
  index: number
  steps: DraftStep[]
  inputs: DraftInput[]
  plugins: PluginInfo[]
  ctx: SettingContext
}) {
  const plugin = plugins.find((p) => p.id === step.plugin)
  const sentence = sentenceOf(plugin)
  if (!sentence) return null
  const settings = settingsOf(plugin)
  const words = (key: string): string | null => {
    const setting = settings.find((s) => s.key === key)
    if (setting)
      return settingWords(setting, step.config[key], ctx, step.config)
    const spec = plugin?.inputs?.find((i) => i.name === key)
    if (!spec) return key
    const ref = step.inputs[key]
    if (!ref) return null
    const { fitting, others } = sourcesFor(spec, index, steps, inputs, plugins)
    return [...fitting, ...others].find((s) => s.ref === ref)?.words ?? ref
  }
  const pieces = sentence.split(/(\{[a-z_][a-z0-9_]*\})/i)
  return (
    <p className="rounded-md bg-canvas-subtle px-3 py-2 text-sm text-fg">
      {pieces.map((piece, i) => {
        const m = /^\{(.+)\}$/.exec(piece)
        if (!m) return <span key={i}>{piece}</span>
        const said = words(m[1])
        return said === null ? (
          <span key={i} className="text-fg-subtle">
            …
          </span>
        ) : (
          <strong key={i} className="font-semibold">
            {said}
          </strong>
        )
      })}
    </p>
  )
}
