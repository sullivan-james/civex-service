import {
  isMap,
  isSeq,
  parseDocument,
  type Document,
  YAMLMap,
  YAMLSeq,
} from 'yaml'

/**
 * A workflow as the builder edits it, read from and written back into its
 * YAML. The YAML stays the workflow (it is what is saved, shared and run);
 * this is only the part a form shows. Writing changes only the keys the form
 * owns, on the document as it was parsed, so comments, key order and keys the
 * form knows nothing about (a step's `timeout`, an input's `description`)
 * survive a round trip through the builder.
 */

export interface DraftStep {
  id: string
  plugin: string
  config: Record<string, unknown>
  /** input name -> "step_id.output_name" (or "__input__.name") */
  inputs: Record<string, string>
  /** The step's `if:`, or '' for none. */
  condition: string
}

export interface DraftInput {
  /** The key steps use: `__input__.<key>`. */
  key: string
  type: 'files' | 'value'
  label: string
}

export interface WorkflowDraft {
  name: string
  description: string
  enabled: boolean
  /** The kind of record it runs on. */
  schema: string
  onCreated: boolean
  onUpdated: boolean
  /** The fields whose change starts it; empty = any field. */
  watchFields: string[]
  inputs: DraftInput[]
  steps: DraftStep[]
}

export const INPUT_SOURCE = '__input__'

export function emptyDraft(): WorkflowDraft {
  return {
    name: '',
    description: '',
    enabled: false,
    schema: '',
    onCreated: false,
    onUpdated: false,
    watchFields: [],
    inputs: [],
    steps: [],
  }
}

function plain(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

function stringMap(value: unknown): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(plain(value))) out[k] = text(v)
  return out
}

export type ReadResult =
  { ok: true; draft: WorkflowDraft } | { ok: false; problem: string }

/** The draft a workflow's YAML describes, or why the builder can't show it
 * (it doesn't parse, or isn't a workflow's shape). */
export function readDraft(content: string): ReadResult {
  const doc = parseDocument(content)
  if (doc.errors.length > 0) {
    return { ok: false, problem: doc.errors[0].message.split('\n')[0] }
  }
  const raw = doc.toJS() as unknown
  if (raw === null || raw === undefined)
    return { ok: true, draft: emptyDraft() }
  if (typeof raw !== 'object' || Array.isArray(raw)) {
    return {
      ok: false,
      problem: 'A workflow is a set of keys (name, steps, …).',
    }
  }
  const wf = raw as Record<string, unknown>
  if (wf.steps !== undefined && !Array.isArray(wf.steps)) {
    return { ok: false, problem: '`steps` must be a list.' }
  }
  const triggers = plain(wf.triggers)
  const created = triggers.record_created
    ? plain(triggers.record_created)
    : null
  const updated = triggers.record_updated
    ? plain(triggers.record_updated)
    : null
  const steps = ((wf.steps as unknown[]) ?? []).map((s) => {
    const step = plain(s)
    return {
      id: text(step.id),
      plugin: text(step.plugin),
      config: { ...plain(step.config) },
      inputs: stringMap(step.inputs),
      condition: text(step.if),
    }
  })
  const inputs = Object.entries(plain(wf.inputs)).map(([key, v]) => {
    const decl = plain(v)
    return {
      key,
      type: decl.type === 'value' ? ('value' as const) : ('files' as const),
      label: text(decl.label),
    }
  })
  return {
    ok: true,
    draft: {
      name: text(wf.name),
      description: text(wf.description),
      enabled: wf.enabled !== false,
      schema:
        text(wf.record_schema) ||
        text(created?.schema) ||
        text(updated?.schema),
      onCreated: created !== null,
      onUpdated: updated !== null,
      watchFields: Array.isArray(updated?.fields)
        ? (updated.fields as unknown[]).map(text)
        : [],
      inputs,
      steps,
    },
  }
}

type Doc = Document.Parsed | Document

/** Set `key` on `map` to `value`, or remove it when `value` is undefined;
 * a value that is already there is left as it is (with its comments). */
function put(doc: Doc, map: YAMLMap, key: string, value: unknown) {
  if (value === undefined) {
    map.delete(key)
    return
  }
  const current = map.get(key, true)
  const now =
    current && typeof current === 'object' && 'toJSON' in current
      ? (current as { toJSON: () => unknown }).toJSON()
      : current
  if (JSON.stringify(now) === JSON.stringify(value)) return
  map.set(key, doc.createNode(value))
}

/** The map at `key` inside `map`, made when it isn't one. */
function mapAt(doc: Doc, map: YAMLMap, key: string): YAMLMap {
  const node = map.get(key, true)
  if (isMap(node)) return node as YAMLMap
  const made = doc.createNode({}) as YAMLMap
  map.set(key, made)
  return made
}

/** Keep `map`'s entries in the order of `keys` (each must be in it), others
 * after them, as they were. */
function syncKeys(doc: Doc, map: YAMLMap, values: Record<string, unknown>) {
  for (const pair of [...map.items]) {
    const k = text((pair.key as { value?: unknown })?.value ?? pair.key)
    if (!(k in values)) map.delete(k)
  }
  for (const [k, v] of Object.entries(values)) put(doc, map, k, v)
}

function blank(value: unknown): boolean {
  return (
    value === undefined ||
    value === null ||
    value === '' ||
    (Array.isArray(value) && value.length === 0)
  )
}

/** `content` with `draft` written into it. Only what the form owns changes;
 * a step keeps its node (and comments) when its id is kept. */
export function writeDraft(content: string, draft: WorkflowDraft): string {
  const doc = parseDocument(content || '{}')
  if (!isMap(doc.contents))
    doc.contents = doc.createNode({}) as unknown as typeof doc.contents
  const root = doc.contents as YAMLMap

  put(doc, root, 'name', draft.name)
  put(doc, root, 'description', draft.description || undefined)
  // Off is written; on is the default, so a file without the key stays so.
  if (!draft.enabled) put(doc, root, 'enabled', false)
  else if (root.has('enabled')) put(doc, root, 'enabled', true)
  put(doc, root, 'record_schema', draft.schema || undefined)

  if (draft.schema && (draft.onCreated || draft.onUpdated)) {
    const triggers = mapAt(doc, root, 'triggers')
    if (draft.onCreated) {
      put(doc, mapAt(doc, triggers, 'record_created'), 'schema', draft.schema)
    } else triggers.delete('record_created')
    if (draft.onUpdated) {
      const upd = mapAt(doc, triggers, 'record_updated')
      put(doc, upd, 'schema', draft.schema)
      put(
        doc,
        upd,
        'fields',
        draft.watchFields.length ? draft.watchFields : undefined,
      )
    } else triggers.delete('record_updated')
  } else root.delete('triggers')

  if (draft.inputs.length > 0) {
    const inputs = mapAt(doc, root, 'inputs')
    const keep = new Set(draft.inputs.map((i) => i.key))
    for (const pair of [...inputs.items]) {
      const k = text((pair.key as { value?: unknown })?.value ?? pair.key)
      if (!keep.has(k)) inputs.delete(k)
    }
    for (const input of draft.inputs) {
      const decl = mapAt(doc, inputs, input.key)
      put(doc, decl, 'type', input.type)
      put(doc, decl, 'label', input.label || undefined)
    }
  } else root.delete('inputs')

  const oldSteps = root.get('steps', true)
  const byId = new Map<string, YAMLMap>()
  if (isSeq(oldSteps)) {
    for (const item of oldSteps.items) {
      if (isMap(item)) byId.set(text(item.get('id')), item as YAMLMap)
    }
  }
  const steps = draft.steps.map((step) => {
    const node = byId.get(step.id) ?? (doc.createNode({}) as YAMLMap)
    put(doc, node, 'id', step.id)
    put(doc, node, 'plugin', step.plugin)
    const config = Object.fromEntries(
      Object.entries(step.config).filter(([, v]) => !blank(v)),
    )
    if (Object.keys(config).length)
      syncKeys(doc, mapAt(doc, node, 'config'), config)
    else node.delete('config')
    const inputs = Object.fromEntries(
      Object.entries(step.inputs).filter(([, v]) => !blank(v)),
    )
    if (Object.keys(inputs).length)
      syncKeys(doc, mapAt(doc, node, 'inputs'), inputs)
    else node.delete('inputs')
    put(doc, node, 'if', step.condition.trim() || undefined)
    return node
  })
  const seq = isSeq(oldSteps) ? oldSteps : new YAMLSeq()
  seq.items = steps
  if (!isSeq(oldSteps)) root.set('steps', seq)
  const out = doc.toString({ lineWidth: 0, flowCollectionPadding: false })
  // Nothing the form owns changed: the file is left exactly as it was.
  const before = parseDocument(content || '{}').toJS()
  return JSON.stringify(doc.toJS()) === JSON.stringify(before) && content
    ? content
    : out
}

/** An id for a new step from its action's name, not used by another step:
 * `read_a_file`, `read_a_file_2`, … */
export function newStepId(base: string, taken: Iterable<string>): string {
  const slug =
    base
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 40) || 'step'
  const used = new Set(taken)
  if (!used.has(slug)) return slug
  for (let n = 2; ; n++) if (!used.has(`${slug}_${n}`)) return `${slug}_${n}`
}

/** A file name stem from a workflow's name: what a new one is saved as. */
export function stemFor(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 60) || 'workflow'
  )
}
