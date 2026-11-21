/**
 * The explorer's Summary: which groupings and measures a person chose, held
 * in the address as the server writes them (`sum.by=site.region,taken:month`,
 * `sum.m=count,mean:depth`; see civex/domain/summary.py), and which of the
 * listed kind's fields can be grouped by or measured (from the field types'
 * `grouping` and `measures`, the one table).
 */

import type { FieldTypeDescriptor } from '../api/schemas'
import type { SavedSummary } from '../api/views'
import type { FilterableField } from './hierarchy'
import type { FilterTreeWire } from './filterTree'

/** A comma-separated address value as a list (empty: none). */
export function splitKeys(raw: string | null | undefined): string[] {
  return (raw ?? '')
    .split(',')
    .map((k) => k.trim())
    .filter(Boolean)
}

/** A field as a summary names it: its own name, or `kind.name` for a field
 * of a kind above the one listed. */
export function fieldKey(f: FilterableField): string {
  return f.relation === 'self' ? f.name : `${f.sourceSchemaName}.${f.name}`
}

/** `site.region:month` -> the field part and how it is grouped. */
export function splitGroupKey(key: string): { field: string; how: string } {
  const at = key.indexOf(':')
  return at < 0
    ? { field: key, how: '' }
    : { field: key.slice(0, at), how: key.slice(at + 1) }
}

/** The fields a summary of the listed kind can use: its own and those of the
 * kinds above it (a record has many of a kind beneath it, so those can't). */
export function summaryFields(
  fields: FilterableField[],
  types: FieldTypeDescriptor[],
): { field: FilterableField; type: FieldTypeDescriptor }[] {
  const byType = new Map(types.map((t) => [t.type, t]))
  return fields.flatMap((field) => {
    const type = byType.get(field.type)
    return type && field.relation !== 'descendant' ? [{ field, type }] : []
  })
}

/** A group's condition added to the explorer's filter: what drilling into it
 * lists. */
export function withCondition(
  filter: FilterTreeWire | null,
  where: FilterTreeWire,
): FilterTreeWire {
  return filter ? { and: [filter, where] } : where
}

/** A cell of a summary as a person reads it. */
export function formatSummaryValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'number')
    return value.toLocaleString(undefined, { maximumFractionDigits: 4 })
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

/** Sort rows by a column (a group's value or a measure), blanks last. */
export function compareSummaryCells(a: unknown, b: unknown): number {
  if (a === b) return 0
  if (a === null || a === undefined) return 1
  if (b === null || b === undefined) return -1
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b), undefined, { numeric: true })
}

/** The explorer's Summary choices, as the address holds them (`sum.by`,
 * `sum.m`, `sum.sort`, `sum.view`, `sum.y`). */
export const SUMMARY_NS = 'sum.'
export const SUMMARY_PICKS = ['by', 'm', 'view', 'y'] as const

/** The groupings a summary starts with when none is chosen, so the screen is
 * never blank: the first field of the listed kind (else of a kind above) that
 * reads as categories (a list of choices, true/false) or a date by month;
 * none (a single total) when there is no such field. */
export function defaultGrouping(
  usable: { field: FilterableField; type: FieldTypeDescriptor }[],
): string[] {
  const score = ({
    field,
    type,
  }: {
    field: FilterableField
    type: FieldTypeDescriptor
  }): number => {
    if (!type.grouping) return 0
    const choices = field.restrictions?.choices
    if (field.type === 'enum' || (Array.isArray(choices) && choices.length))
      return 3
    if (field.type === 'boolean') return 2
    if (type.grouping === 'bucket' && type.buckets.includes('month')) return 1
    return 0
  }
  const ranked = usable
    .map((u, i) => ({ u, i, s: score(u) }))
    .filter((x) => x.s > 0)
    // Own fields first, then the best kind of grouping, then field order.
    .sort(
      (a, b) =>
        Number(b.u.field.relation === 'self') -
          Number(a.u.field.relation === 'self') ||
        b.s - a.s ||
        a.i - b.i,
    )
  if (ranked.length === 0) return []
  const best = ranked[0].u
  const key = fieldKey(best.field)
  return [best.type.grouping === 'bucket' ? `${key}:month` : key]
}

const PERIOD_WORDS: Record<string, string> = {
  year: 'by year',
  month: 'by month',
  week: 'by week',
  day: 'by day',
}

/** How a grouping's values are put in groups, in plain words: "by month",
 * "in ranges of 5 m", "each value", "each item". */
export function groupingWords(
  how: string,
  type: FieldTypeDescriptor | undefined,
  unit?: string | null,
): string {
  if (type?.grouping === 'each') return 'each item'
  if (!how) return 'each value'
  if (PERIOD_WORDS[how]) return PERIOD_WORDS[how]
  return `in ranges of ${how}${unit ? ` ${unit}` : ''}`
}

/** What the address says about the Summary, read once. */
export interface SummaryChoices {
  by: string[]
  /** As chosen (empty: only a count). */
  measures: string[]
  sort: { column: string; direction: 'asc' | 'desc' } | null
  show: 'table' | 'chart'
  y: string | null
}

export function summaryChoices(sp: URLSearchParams): SummaryChoices {
  const raw = sp.get(`${SUMMARY_NS}sort`) ?? ''
  const cut = raw.lastIndexOf(':')
  const column = cut < 0 ? raw : raw.slice(0, cut)
  return {
    by: splitKeys(sp.get(`${SUMMARY_NS}by`)),
    measures: splitKeys(sp.get(`${SUMMARY_NS}m`)),
    sort: column
      ? {
          column,
          direction: cut >= 0 && raw.slice(cut + 1) === 'desc' ? 'desc' : 'asc',
        }
      : null,
    show: sp.get(`${SUMMARY_NS}view`) === 'chart' ? 'chart' : 'table',
    y: sp.get(`${SUMMARY_NS}y`) || null,
  }
}

/** The Summary on screen as a saved analysis keeps it: its choices (the
 * groupings shown, defaults included, so it opens the same), and where it was
 * made. */
export function savedSummaryOf(
  choices: SummaryChoices,
  by: string[],
  where: {
    collection: string | null
    within: string | null
    search: string | null
  },
): SavedSummary {
  const measures = choices.measures.length ? choices.measures : ['count']
  const keys = new Set([...by, ...measures])
  return {
    group_by: by,
    measures,
    sort: choices.sort && keys.has(choices.sort.column) ? choices.sort : null,
    show: choices.show,
    chart_measure: choices.y && measures.includes(choices.y) ? choices.y : null,
    collection: where.collection,
    within: where.within,
    search: where.search,
  }
}

/** A saved analysis put into the address: the explorer's Summary with its
 * choices, the search and record it was made with. The view's own filter is
 * the explorer's (`viewPatch`). */
export function withSavedSummary(
  prev: URLSearchParams,
  saved: SavedSummary,
): URLSearchParams {
  const out = new URLSearchParams(prev)
  for (const k of [...SUMMARY_PICKS, 'sort', 'page']) out.delete(SUMMARY_NS + k)
  out.set('show', 'summary')
  // An empty grouping is a choice too (a single total), kept apart from "not
  // chosen" (the default grouping) by an explicit empty value.
  out.set(`${SUMMARY_NS}by`, saved.group_by.join(','))
  const m = saved.measures
  if (!(m.length === 1 && m[0] === 'count'))
    out.set(`${SUMMARY_NS}m`, m.join(','))
  if (saved.sort)
    out.set(`${SUMMARY_NS}sort`, `${saved.sort.column}:${saved.sort.direction}`)
  if (saved.show === 'chart') out.set(`${SUMMARY_NS}view`, 'chart')
  if (saved.chart_measure) out.set(`${SUMMARY_NS}y`, saved.chart_measure)
  if (saved.search) out.set('q', saved.search)
  else out.delete('q')
  if (saved.within) out.set('within', saved.within)
  return out
}
