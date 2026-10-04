import type { RunFilterField } from '../api/workflows'
import type { FilterableField } from './hierarchy'
import type { FilterConditionWire, FilterTreeWire } from './filterTree'

/** What the filter chips call the thing being listed, in place of a schema. */
export const RUN_LIST = 'run'

/** The run fields as the filter builder's fields, so runs are filtered with the
 * same controls as records. `choices` fills the ones the server can't list
 * itself: the workflows and schemas that exist, and the failure types known. */
export function runFilterFields(
  fields: RunFilterField[] | undefined,
  choices: Record<string, string[]>,
): FilterableField[] {
  return (fields ?? []).map((f) => {
    const options = f.choices ?? choices[f.name]
    return {
      id: `run-${f.name}`,
      name: f.name,
      label: f.label,
      type: options ? 'enum' : f.type,
      required: false,
      restrictions: options ? { choices: options } : {},
      default: null,
      position: null,
      sourceSchemaName: RUN_LIST,
      relation: 'self',
      operators: f.operators,
      ownerless: true,
    } as FilterableField
  })
}

const cond = (
  field: string,
  op: FilterConditionWire['op'],
  value?: unknown,
): FilterConditionWire => ({ field, op, value })

/** All of these must hold. */
export function allOf(...terms: FilterTreeWire[]): FilterTreeWire | null {
  // An AND inside an AND is the same thing flat, and reads as one list of chips.
  const list = terms
    .filter(Boolean)
    .flatMap((t) => ('and' in t && t.and ? t.and : [t]))
  if (list.length === 0) return null
  return list.length === 1 ? list[0] : { and: list }
}

export const failedRuns = (): FilterTreeWire => cond('status', 'eq', 'failed')

/** Runs queued at or after an instant, e.g. the start of a batch. */
export const queuedSince = (iso: string): FilterTreeWire =>
  cond('created_at', 'gte', iso)

/** The conditions to add for one group of failures. */
export function failureGroupFilter(g: {
  workflow: string
  kind: string | null
  message: string | null
}): FilterTreeWire {
  return allOf(
    failedRuns(),
    cond('workflow', 'eq', g.workflow),
    ...(g.kind ? [cond('error_kind', 'eq', g.kind)] : []),
    ...(g.message ? [cond('error', 'eq', g.message)] : []),
  )!
}

/** The address a person lands on to look at failures: failed runs, optionally
 * only those queued since some instant. */
export function failedRunsHref(since?: string): string {
  const tree = since ? allOf(failedRuns(), queuedSince(since))! : failedRuns()
  return `/runs?filter=${encodeURIComponent(JSON.stringify(tree))}`
}

/** Older links name `status`, `trigger` and `workflow` directly; the same thing
 * as a filter. */
export function legacyRunFilter(picks: {
  status?: string
  trigger?: string
  workflow?: string
}): FilterTreeWire | null {
  return allOf(
    ...(picks.workflow ? [cond('workflow', 'eq', picks.workflow)] : []),
    ...(picks.status ? [cond('status', 'eq', picks.status)] : []),
    ...(picks.trigger ? [cond('trigger', 'eq', picks.trigger)] : []),
  )
}

/** `tree` with one more condition ANDed in. */
export function withCondition(
  tree: FilterTreeWire | null,
  more: FilterTreeWire,
): FilterTreeWire {
  return allOf(...(tree ? [tree] : []), more)!
}

/** `tree` without the top-level conditions that test any of these fields. */
export function withoutFields(
  tree: FilterTreeWire | null,
  fields: string[],
): FilterTreeWire | null {
  if (!tree) return null
  const terms = 'and' in tree && tree.and ? tree.and : [tree]
  return allOf(
    ...terms.filter((t) => !('field' in t && fields.includes(t.field))),
  )
}

/** A failure message cut to `max` characters for a line of a list; the whole
 * message belongs in a tooltip or on the run's page. */
export function truncate(text: string, max = 140): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length <= max ? flat : `${flat.slice(0, max - 1).trimEnd()}…`
}
