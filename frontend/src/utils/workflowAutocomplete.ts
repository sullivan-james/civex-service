import type { PluginInfo } from '../api/plugins'

export interface Suggestion {
  /** Text inserted in place of the matched prefix. */
  insertText: string
  /** What's shown in the dropdown. */
  label: string
  detail?: string
}

export interface AutocompleteContext {
  kind: 'plugin' | 'config-key' | 'input-value'
  /** Absolute offsets into the full text the suggestion replaces. */
  replaceFrom: number
  replaceTo: number
}

interface StepBlock {
  id: string
  plugin: string | null
  startLine: number
  endLine: number
  itemIndent: number
}

function stripQuotes(s: string): string {
  const trimmed = s.trim()
  if (
    trimmed.length >= 2 &&
    ((trimmed[0] === '"' && trimmed[trimmed.length - 1] === '"') ||
      (trimmed[0] === "'" && trimmed[trimmed.length - 1] === "'"))
  ) {
    return trimmed.slice(1, -1)
  }
  return trimmed
}

function indentOf(line: string): number {
  return line.length - line.trimStart().length
}

/** Finds `- id: <step_id>` list items and the plugin id declared inside each. */
function parseStepBlocks(lines: string[]): StepBlock[] {
  const stepStartRe = /^(\s*)-\s+id:\s*(.+?)\s*$/
  const starts: { line: number; indent: number; id: string }[] = []
  lines.forEach((line, i) => {
    const m = stepStartRe.exec(line)
    if (m) starts.push({ line: i, indent: m[1].length, id: stripQuotes(m[2]) })
  })

  return starts.map(({ line: startLine, indent, id }) => {
    let endLine = lines.length - 1
    for (let j = startLine + 1; j < lines.length; j++) {
      if (lines[j].trim() === '') continue
      if (indentOf(lines[j]) <= indent) {
        endLine = j - 1
        break
      }
    }
    let plugin: string | null = null
    for (let j = startLine; j <= endLine; j++) {
      const pm = /^\s*plugin:\s*(.+?)\s*$/.exec(lines[j])
      if (pm) {
        plugin = stripQuotes(pm[1])
        break
      }
    }
    return { id, plugin, startLine, endLine, itemIndent: indent }
  })
}

/** Finds a `<key>:` block (e.g. `config:`, `inputs:`) within [startLine, endLine]
 * and returns the line range of its (still-nested) children, or null if absent. */
function findSubBlock(
  lines: string[],
  key: string,
  startLine: number,
  endLine: number,
): { headerLine: number; headerIndent: number; lastChildLine: number } | null {
  const headerRe = new RegExp(`^(\\s*)${key}:\\s*$`)
  for (let j = startLine; j <= endLine; j++) {
    const m = headerRe.exec(lines[j])
    if (!m) continue
    const headerIndent = m[1].length
    let lastChildLine = j
    for (let k = j + 1; k <= endLine; k++) {
      if (lines[k].trim() === '') continue
      if (indentOf(lines[k]) <= headerIndent) break
      lastChildLine = k
    }
    return { headerLine: j, headerIndent, lastChildLine }
  }
  return null
}

function lineStartOffsets(lines: string[]): number[] {
  const offsets: number[] = [0]
  for (const line of lines) {
    offsets.push(offsets[offsets.length - 1] + line.length + 1)
  }
  return offsets
}

function lineIndexAtOffset(offsets: number[], cursor: number): number {
  for (let i = offsets.length - 1; i >= 0; i--) {
    if (offsets[i] <= cursor) return i
  }
  return -1
}

/** Determines what, if anything, should be autocompleted at `cursor`. */
export function getAutocompleteContext(
  text: string,
  cursor: number,
): AutocompleteContext | null {
  const lines = text.split('\n')
  const offsets = lineStartOffsets(lines)
  const lineIdx = lineIndexAtOffset(offsets, cursor)
  if (lineIdx < 0 || lineIdx >= lines.length) return null
  const line = lines[lineIdx]
  const col = cursor - offsets[lineIdx]
  const upToCursor = line.slice(0, col)

  // `plugin: <prefix>`
  const pluginMatch = /^\s*plugin:\s*([^\s#]*)$/.exec(upToCursor)
  if (pluginMatch) {
    const prefix = pluginMatch[1]
    return {
      kind: 'plugin',
      replaceFrom: cursor - prefix.length,
      replaceTo: cursor,
    }
  }

  const blocks = parseStepBlocks(lines)
  const block = blocks.find(
    (b) => b.startLine <= lineIdx && lineIdx <= b.endLine,
  )
  if (!block) return null

  // bare `<prefix>` key position inside a `config:` sub-block
  const configBlock = findSubBlock(
    lines,
    'config',
    block.startLine,
    block.endLine,
  )
  if (
    configBlock &&
    lineIdx > configBlock.headerLine &&
    lineIdx <= configBlock.lastChildLine
  ) {
    const keyMatch = /^(\s*)([\w-]*)$/.exec(upToCursor)
    if (keyMatch && keyMatch[1].length > configBlock.headerIndent) {
      const prefix = keyMatch[2]
      return {
        kind: 'config-key',
        replaceFrom: cursor - prefix.length,
        replaceTo: cursor,
      }
    }
  }

  // value position (`<input name>: <prefix>`) inside an `inputs:` sub-block
  const inputsBlock = findSubBlock(
    lines,
    'inputs',
    block.startLine,
    block.endLine,
  )
  if (
    inputsBlock &&
    lineIdx > inputsBlock.headerLine &&
    lineIdx <= inputsBlock.lastChildLine
  ) {
    const valueMatch = /^(\s*)[\w-]+:\s*(\S*)$/.exec(upToCursor)
    if (valueMatch && valueMatch[1].length > inputsBlock.headerIndent) {
      const prefix = valueMatch[2]
      return {
        kind: 'input-value',
        replaceFrom: cursor - prefix.length,
        replaceTo: cursor,
      }
    }
  }

  return null
}

/** Plugin ids matching whatever's already typed after `plugin:`. */
function pluginIdSuggestions(
  plugins: PluginInfo[],
  prefix: string,
): Suggestion[] {
  return plugins
    .filter((p) => p.id.toLowerCase().startsWith(prefix.toLowerCase()))
    .sort(
      (a, b) =>
        Number(b.builtin) - Number(a.builtin) || a.id.localeCompare(b.id),
    )
    .map((p) => ({ insertText: p.id, label: p.id, detail: p.description }))
}

/** Config keys declared by the step's own plugin, minus ones already set. */
function configKeySuggestions(
  plugins: PluginInfo[],
  text: string,
  cursor: number,
  prefix: string,
): Suggestion[] {
  const lines = text.split('\n')
  const offsets = lineStartOffsets(lines)
  const lineIdx = lineIndexAtOffset(offsets, cursor)
  const blocks = parseStepBlocks(lines)
  const block = blocks.find(
    (b) => b.startLine <= lineIdx && lineIdx <= b.endLine,
  )
  if (!block?.plugin) return []
  const plugin = plugins.find((p) => p.id === block.plugin)
  if (!plugin) return []

  const configBlock = findSubBlock(
    lines,
    'config',
    block.startLine,
    block.endLine,
  )
  const usedKeys = new Set<string>()
  if (configBlock) {
    for (
      let j = configBlock.headerLine + 1;
      j <= configBlock.lastChildLine;
      j++
    ) {
      if (j === lineIdx) continue
      const km = /^\s*([\w-]+):/.exec(lines[j])
      if (km) usedKeys.add(km[1])
    }
  }

  return Object.entries(plugin.config_schema.properties ?? {})
    .filter(
      ([key]) =>
        !usedKeys.has(key) &&
        key.toLowerCase().startsWith(prefix.toLowerCase()),
    )
    .map(([key, prop]) => ({
      insertText: `${key}: `,
      label: key,
      detail: prop.type ?? 'any',
    }))
}

/** `step_id.output_name` references to steps declared earlier in the file. */
function stepOutputSuggestions(
  plugins: PluginInfo[],
  text: string,
  cursor: number,
  prefix: string,
): Suggestion[] {
  const lines = text.split('\n')
  const offsets = lineStartOffsets(lines)
  const lineIdx = lineIndexAtOffset(offsets, cursor)
  const blocks = parseStepBlocks(lines)
  const block = blocks.find(
    (b) => b.startLine <= lineIdx && lineIdx <= b.endLine,
  )
  if (!block) return []

  const suggestions: Suggestion[] = []
  for (const earlier of blocks) {
    if (earlier.startLine >= block.startLine || !earlier.plugin) continue
    const plugin = plugins.find((p) => p.id === earlier.plugin)
    if (!plugin?.outputs) continue
    for (const output of plugin.outputs) {
      const value = `${earlier.id}.${output.name}`
      if (value.toLowerCase().startsWith(prefix.toLowerCase())) {
        suggestions.push({
          insertText: value,
          label: value,
          detail: output.type,
        })
      }
    }
  }
  return suggestions
}

export function getSuggestions(
  context: AutocompleteContext,
  plugins: PluginInfo[],
  text: string,
): Suggestion[] {
  const prefix = text.slice(context.replaceFrom, context.replaceTo)
  switch (context.kind) {
    case 'plugin':
      return pluginIdSuggestions(plugins, prefix)
    case 'config-key':
      return configKeySuggestions(plugins, text, context.replaceFrom, prefix)
    case 'input-value':
      return stepOutputSuggestions(plugins, text, context.replaceFrom, prefix)
    default:
      return []
  }
}
