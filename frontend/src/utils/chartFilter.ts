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

/** Where the tree's one simple term about the chart's field is (-1: none,
 * or the field is used in a way a chart can't show). */
function simpleTermIndex(
  tree: FilterTreeWire | null,
  of: BarField,
  listed: string,
): number {
  const terms = topLevelTerms(tree)
  const touching = terms
    .map((t, i) => (mentions(t, of, listed) ? i : -1))
    .filter((i) => i >= 0)
  if (touching.length !== 1) return -1
  return about(terms[touching[0]], of, listed) ? touching[0] : -1
}

/** The filter a chart counts with: the explorer's, without the simple
 * condition on the chart's own field (so its other bars stay to click). */
export function filterForChart(
  tree: FilterTreeWire | null,
  of: BarField | undefined,
  listed: string,
): FilterTreeWire | null {
  if (!of) return tree
  const at = simpleTermIndex(tree, of, listed)
  if (at < 0) return tree
  return rebuild(topLevelTerms(tree).filter((_, i) => i !== at))
}

/** A test for "is this bar chosen?": true for a bar whose condition the
 * tree's simple term about the field allows. Null when nothing is lit. */
export function litBars(
  tree: FilterTreeWire | null,
  of: BarField | undefined,
  listed: string,
): ((where: FilterTreeWire | null) => boolean) | null {
  if (!of) return null
  const at = simpleTermIndex(tree, of, listed)
  if (at < 0) return null
  const chosen = new Set(alternatives(topLevelTerms(tree)[at]).map(key))
  return (where) =>
    !!where && alternatives(where).every((alt) => chosen.has(key(alt)))
}

/** Click a bar: its condition goes into the tree, or comes out when it was
 * there. Several bars of one chart are alternatives of one term. */
export function toggleBar(
  tree: FilterTreeWire | null,
  where: FilterTreeWire,
  of: BarField | undefined,
  listed: string,
): FilterTreeWire | null {
  const terms = topLevelTerms(tree)
  const at = of ? simpleTermIndex(tree, of, listed) : -1
  if (at < 0) return rebuild([...terms, where])
  const have = alternatives(terms[at])
  const clicked = alternatives(where)
  const clickedKeys = new Set(clicked.map(key))
  const haveKeys = new Set(have.map(key))
  const on = clicked.every((alt) => haveKeys.has(key(alt)))
  const next = on
    ? have.filter((alt) => !clickedKeys.has(key(alt)))
    : [...have, ...clicked.filter((alt) => !haveKeys.has(key(alt)))]
  const term = termOf(next)
  const out = [...terms]
  if (term) out[at] = term
  else out.splice(at, 1)
  return rebuild(out)
}
