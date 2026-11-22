/**
 * Charts and the filter are one thing: clicking a bar adds or removes a
 * condition in the explorer's own filter tree (`utils/filterTree`), so a
 * filter made from charts and one made in the builder are the same, and
 * either can be edited, shown as chips, saved or shared.
 *
 * A chart's bars are lit, and the chart leaves the condition on its own
 * field out of what it counts, only while the tree holds exactly ONE simple
 * top-level term about that field: a value ("is"), several ("is any of", or
 * an OR of values), a range (a number's step, a date's period) or empty.
 * Anything else (the field inside a group with other fields, "is not", two
 * terms about it) is left exactly as written: the chart then just counts
 * the filtered records with nothing lit, and a click adds its condition.
 */

import type { RecordSelectionBody, SummaryRequest } from '../api/records'
import type { FilterConditionWire, FilterTreeWire } from './filterTree'
import { topLevelTerms } from './filterLabels'

/** The field a chart's bars are of, as the summary names it. */
export interface BarField {
  field: string
  schema_name: string
}

const isGroup = (
  w: FilterTreeWire,
): w is { and?: FilterTreeWire[]; or?: FilterTreeWire[] } =>
  'and' in w || 'or' in w

const SIMPLE_OPS = new Set(['eq', 'in', 'is_null', 'gte', 'lt'])

function onField(
  leaf: FilterConditionWire,
  of: BarField,
  listed: string,
): boolean {
  return leaf.field === of.field && (leaf.schema ?? listed) === of.schema_name
}

/** Whether every condition in `term` is a simple one on the chart's field. */
function about(term: FilterTreeWire, of: BarField, listed: string): boolean {
  if (isGroup(term)) {
    const children = term.and ?? term.or ?? []
    return children.length > 0 && children.every((c) => about(c, of, listed))
  }
  return onField(term, of, listed) && SIMPLE_OPS.has(term.op)
}

/** Whether `term` tests the chart's field anywhere inside it. */
function mentions(term: FilterTreeWire, of: BarField, listed: string): boolean {
  if (isGroup(term))
    return (term.and ?? term.or ?? []).some((c) => mentions(c, of, listed))
  return onField(term, of, listed)
}

/** One thing a bar can stand for, written one way so two can be compared:
 * a value, empty, or a range. */
function key(alt: FilterTreeWire): string {
  if (isGroup(alt)) {
    const parts = (alt.and ?? alt.or ?? []).map(key).sort()
    return `${'and' in alt ? 'and' : 'or'}(${parts.join(',')})`
  }
  return `${alt.op}:${alt.op === 'is_null' ? '' : JSON.stringify(alt.value)}`
}

/** A term (or a bar's own condition) as the alternatives it allows: the
 * members of an OR, each value of an "is any of", else itself. */
function alternatives(term: FilterTreeWire): FilterTreeWire[] {
  if (isGroup(term)) {
    if ('or' in term) return (term.or ?? []).flatMap(alternatives)
    return [term]
  }
  if (term.op === 'in' && Array.isArray(term.value))
    return term.value.map((value) => ({ ...term, op: 'eq' as const, value }))
  return [term]
}

/** Alternatives back as one term: values together as "is any of", the rest
 * beside them in an OR. Null when nothing is left. */
function termOf(alts: FilterTreeWire[]): FilterTreeWire | null {
  if (alts.length === 0) return null
  const values = alts.filter(
    (a): a is FilterConditionWire => !isGroup(a) && a.op === 'eq',
  )
  const rest = alts.filter((a) => isGroup(a) || a.op !== 'eq')
  const parts: FilterTreeWire[] = [...rest]
  if (values.length === 1) parts.unshift(values[0])
  else if (values.length > 1)
    parts.unshift({
      ...values[0],
      op: 'in',
      value: values.map((v) => v.value),
    })
  return parts.length === 1 ? parts[0] : { or: parts }
}

function rebuild(terms: FilterTreeWire[]): FilterTreeWire | null {
  if (terms.length === 0) return null
  return terms.length === 1 ? terms[0] : { and: terms }
}

/** The tree's simple choice about the chart's field: which top-level terms
 * hold it and the alternatives it allows. It is one term (a value, several,
 * a range, an OR of them), or a range written flat as two terms ("from" and
 * "under": what a lone range is when it is the whole filter, since an AND
 * of two conditions reads as two terms). Null when the field isn't used, or
 * is used in a way a chart can't show. */
function chosen(
  tree: FilterTreeWire | null,
  of: BarField,
  listed: string,
): { at: number[]; alts: FilterTreeWire[] } | null {
  const terms = topLevelTerms(tree)
  const at = terms
    .map((t, i) => (mentions(t, of, listed) ? i : -1))
    .filter((i) => i >= 0)
  if (at.length === 1 && about(terms[at[0]], of, listed))
    return { at, alts: alternatives(terms[at[0]]) }
  if (at.length === 2) {
    const [a, b] = at.map((i) => terms[i])
    const ops = [a, b].map((t) => (isGroup(t) ? '' : t.op)).sort()
    if (ops[0] === 'gte' && ops[1] === 'lt')
      return { at, alts: [{ and: [a, b] }] }
  }
  return null
}

/** The filter a chart counts with: the explorer's, without the simple
 * condition on the chart's own field (so its other bars stay to click). */
export function filterForChart(
  tree: FilterTreeWire | null,
  of: BarField | undefined,
  listed: string,
): FilterTreeWire | null {
  const own = of ? chosen(tree, of, listed) : null
  if (!own) return tree
  return rebuild(topLevelTerms(tree).filter((_, i) => !own.at.includes(i)))
}

/** A test for "is this bar chosen?": true for a bar whose condition the
 * tree's simple choice about the field allows. Null when nothing is lit. */
export function litBars(
  tree: FilterTreeWire | null,
  of: BarField | undefined,
  listed: string,
): ((where: FilterTreeWire | null) => boolean) | null {
  const own = of ? chosen(tree, of, listed) : null
  if (!own) return null
  const keys = new Set(own.alts.map(key))
  return (where) =>
    !!where && alternatives(where).every((alt) => keys.has(key(alt)))
}

/** Click a bar: its condition goes into the tree, or comes out when it was
 * there (so clicking the same one again never adds it twice). Several bars
 * of one chart are alternatives of one term. */
export function toggleBar(
  tree: FilterTreeWire | null,
  where: FilterTreeWire,
  of: BarField | undefined,
  listed: string,
): FilterTreeWire | null {
  const terms = topLevelTerms(tree)
  const own = of ? chosen(tree, of, listed) : null
  if (!own) return rebuild([...terms, where])
  const clicked = alternatives(where)
  const clickedKeys = new Set(clicked.map(key))
  const haveKeys = new Set(own.alts.map(key))
  const on = clicked.every((alt) => haveKeys.has(key(alt)))
  const next = on
    ? own.alts.filter((alt) => !clickedKeys.has(key(alt)))
    : [...own.alts, ...clicked.filter((alt) => !haveKeys.has(key(alt)))]
  const term = termOf(next)
  // The choice goes back where it was, as one term.
  const out = terms.filter((_, i) => !own.at.includes(i))
  if (term) out.splice(own.at[0], 0, term)
  return rebuild(out)
}

/** The field a chart's bars are of, from its first grouping (`site`,
 * `kind.field:month`): what a click on a bar filters by. */
export function barFieldOf(
  groupBy: string[],
  listed: string,
): BarField | undefined {
  const first = groupBy[0]
  if (!first) return undefined
  const cut = first.indexOf(':')
  const name = cut < 0 ? first : first.slice(0, cut)
  const dot = name.lastIndexOf('.')
  return dot < 0
    ? { field: name, schema_name: listed }
    : { field: name.slice(dot + 1), schema_name: name.slice(0, dot) }
}

/** What a chart asks the summary: the records it counts, without the
 * condition on its own field where bars filter (`own`), so what is drawn and
 * what is downloaded are the same numbers. Null for a map. */
export function chartRequest(
  chart: { map?: string | null; group_by: string[]; measures: string[] },
  records: RecordSelectionBody,
  own: boolean,
): SummaryRequest | null {
  if (chart.map) return null
  const listed = records.schema_name ?? ''
  const filter = (records.filter ?? null) as FilterTreeWire | null
  return {
    ...records,
    filter: own
      ? filterForChart(filter, barFieldOf(chart.group_by, listed), listed)
      : filter,
    group_by: chart.group_by,
    measures: chart.measures.length ? chart.measures : ['count'],
  }
}
