/**
 * Charts: the one definition (`api/schemas.Chart`, civex/domain/charts.py)
 * as the app writes, names and suggests it. A chart is bars (one bar for
 * each value of a field, each bar showing a count or a number worked out) or
 * a map. Pure: titles in plain words, what the "New chart" panel offers and
 * the address form of a list's unsaved charts. There are no charts by
 * default: a person adds the ones they want.
 */

import type { Chart, FieldTypeDescriptor, Schema } from '../api/schemas'
import type { FilterableField } from './hierarchy'
import { displayLabel } from './naming'
import { fieldKey, splitGroupKey } from './summary'

/** Past this many listed records, charts wait for a click. */
export const CHARTS_AUTO_UP_TO = 200_000
export function newChartId(): string {
  // Never the builder's own address word.
  return `c${Math.random().toString(36).slice(2, 10)}`
}

/** "samples" for a kind's display name: the app's one plural (an "s", as
 * `pluralise` and the explorer's count write it). */
export function plural(label: string): string {
  return `${label.toLowerCase()}s`
}

export type Usable = { field: FilterableField; type: FieldTypeDescriptor }

const fieldLabel = (f: FilterableField) =>
  displayLabel(f.name, f.label).toLowerCase()

function find(usable: Usable[], key: string): Usable | undefined {
  return usable.find((u) => fieldKey(u.field) === key)
}

const PERIODS: Record<string, string> = {
  year: 'year',
  month: 'month',
  week: 'week',
  day: 'day',
}

/** What each bar shows, in plain words: "How many samples", "Average depth". */
export function measureWords(
  measure: string,
  usable: Usable[],
  kind: string,
  schemas: Schema[] = [],
): string {
  const at = measure.indexOf(':')
  const what = at < 0 ? measure : measure.slice(0, at)
  const key = at < 0 ? '' : measure.slice(at + 1)
  if (what === 'count') return `How many ${plural(kind)}`
  if (what === 'inside') {
    const child = schemas.find((s) => s.name === key)
    return `How many ${plural(child ? displayLabel(child.name, child.label) : key)} inside`
  }
  const u = find(usable, key)
  const name = u ? fieldLabel(u.field) : key
  switch (what) {
    case 'mean':
      return `Average ${name}`
    case 'sum':
      return `Total ${name}`
    case 'min':
      return `Smallest ${name}`
    case 'max':
      return `Largest ${name}`
    case 'filled':
      return `How many have ${name}`
    case 'distinct':
      return `Different ${name}`
    default:
      return measure
  }
}

/** "site", "month of taken", "depth in steps of 5 m". */
export function groupWords(group: string, usable: Usable[]): string {
  const { field, how } = splitGroupKey(group)
  const u = find(usable, field)
  const name = u ? fieldLabel(u.field) : field
  if (!how) return name
  if (PERIODS[how]) return `${PERIODS[how]} (${name})`
  const unit = u?.field.restrictions?.unit
  return `${name} in steps of ${how}${unit ? ` ${String(unit)}` : ''}`
}

/** A chart's title: its own, else what it shows ("Average depth per site"). */
export function chartTitle(
  chart: Chart,
  usable: Usable[],
  kind: string,
  schemas: Schema[] = [],
): string {
  if (chart.title) return chart.title
  if (chart.map) return 'Where they are'
  const measure = chart.chart_measure ?? chart.measures[0] ?? 'count'
  const shown = measureWords(measure, usable, kind, schemas)
  if (chart.group_by.length === 0) return shown
  return `${shown} per ${chart.group_by.map((g) => groupWords(g, usable)).join(' and ')}`
}

/** What makes two charts the same chart, whatever their ids. */
function drawn(chart: Chart): string {
  return JSON.stringify(
    chart.map
      ? [chart.title ?? null, chart.map]
      : [
          chart.title ?? null,
          chart.group_by,
          chart.measures,
          chart.chart_measure ?? null,
          chart.show ?? 'chart',
        ],
  )
}

export function sameCharts(a: Chart[], b: Chart[]): boolean {
  return a.length === b.length && a.every((c, i) => drawn(c) === drawn(b[i]))
}

/** A chart as it is saved: only what it says. */
export function storedChart(chart: Chart): Chart {
  const out: Chart = { id: chart.id, group_by: [], measures: [] }
  if (chart.title) out.title = chart.title
  if (chart.map) return { ...out, map: chart.map }
  out.group_by = chart.group_by
  out.measures = chart.measures.length ? chart.measures : ['count']
  if (chart.sort) out.sort = chart.sort
  if (chart.show === 'table') out.show = 'table'
  if (chart.chart_measure) out.chart_measure = chart.chart_measure
  return out
}

// --- the address: a list's own charts, while they differ from the kind's

export const CHARTS_PARAM = 'charts'
/** The chart opened large, or `NEW_CHART` while one is being built. */
export const OPEN_CHART_PARAM = 'chart'
export const NEW_CHART = 'new'

export function chartsToParam(charts: Chart[]): string {
  return JSON.stringify(
    charts.map((c) => {
      const s = storedChart(c)
      return s.map
        ? { i: s.id, t: s.title, map: s.map }
        : {
            i: s.id,
            t: s.title,
            by: s.group_by,
            m: s.measures,
            y: s.chart_measure,
          }
    }),
  )
}

export function chartsFromParam(raw: string | null): Chart[] | null {
  if (raw === null) return null
  try {
    const list = JSON.parse(raw)
    if (!Array.isArray(list)) return null
    return list.map((c) => ({
      id: String(c.i),
      title: c.t ?? null,
      map: c.map ?? null,
      group_by: Array.isArray(c.by) ? c.by.map(String) : [],
      measures: Array.isArray(c.m) ? c.m.map(String) : ['count'],
      chart_measure: c.y ?? null,
    }))
  } catch {
    return null
  }
}

// --- what the "New chart" panel offers

export interface Choice {
  value: string
  label: string
}

/** "One bar for each": the fields whose values can be put in groups. */
export function barFields(usable: Usable[]): Choice[] {
  return usable
    .filter((u) => u.type.grouping)
    .map((u) => ({
      value: fieldKey(u.field),
      label:
        u.field.relation === 'self'
          ? displayLabel(u.field.name, u.field.label)
          : `${displayLabel(u.field.sourceSchemaName)} › ${displayLabel(u.field.name, u.field.label)}`,
    }))
}

/** How a field's bars are cut: a date's periods, a number's steps. */
export function barHow(
  usable: Usable[],
  key: string,
): 'period' | 'steps' | null {
  const u = find(usable, key)
  if (u?.type.grouping === 'bucket') return 'period'
  if (u?.type.grouping === 'bin') return 'steps'
  return null
}

export const PERIOD_CHOICES: Choice[] = [
  { value: 'year', label: 'each year' },
  { value: 'month', label: 'each month' },
  { value: 'week', label: 'each week' },
  { value: 'day', label: 'each day' },
]

/** "Each bar shows": what can be worked out, and whether it needs a field or
 * a kind beneath. */
export const SHOWS: {
  value: string
  label: string
  of: 'field' | 'kind' | null
}[] = [
  { value: 'count', label: 'How many', of: null },
  { value: 'mean', label: 'Average', of: 'field' },
  { value: 'sum', label: 'Total', of: 'field' },
  { value: 'min', label: 'Smallest', of: 'field' },
  { value: 'max', label: 'Largest', of: 'field' },
  { value: 'filled', label: 'How many have', of: 'field' },
  { value: 'inside', label: 'How many inside', of: 'kind' },
]

/** The fields a measure can be worked out over (a kind's own and above). */
export function measureFields(usable: Usable[], measure: string): Choice[] {
  return (
    usable
      .filter((u) => u.type.measures.includes(measure))
      // An average, total, smallest or largest is of a number.
      .filter(
        (u) =>
          measure === 'filled' ||
          u.field.type === 'integer' ||
          u.field.type === 'float',
      )
      .map((u) => ({
        value: fieldKey(u.field),
        label: displayLabel(u.field.name, u.field.label),
      }))
  )
}

/** The kinds beneath `listed`, whose records can be counted inside its. */
export function kindsBeneath(listed: Schema, schemas: Schema[]): Choice[] {
  const out: Choice[] = []
  let level = [listed.id]
  while (level.length) {
    const next = schemas.filter(
      (s) => s.parent_id && level.includes(s.parent_id),
    )
    out.push(
      ...next.map((s) => ({
        value: s.name,
        label: displayLabel(s.name, s.label),
      })),
    )
    level = next.map((s) => s.id)
  }
  return out
}

export function buildChart(pick: {
  by: string
  how: string
  show: string
  of: string
}): Chart {
  const group = pick.by ? [pick.how ? `${pick.by}:${pick.how}` : pick.by] : []
  const measure = pick.show === 'count' ? 'count' : `${pick.show}:${pick.of}`
  return { id: newChartId(), group_by: group, measures: [measure] }
}

export function mapChart(field: FilterableField): Chart {
  return {
    id: newChartId(),
    map: fieldKey(field),
    group_by: [],
    measures: [],
  }
}

// --- recommendations, offered while a chart is being built

/** How many ready-made charts the New chart panel offers. */
export const RECOMMEND_UP_TO = 4

/** Charts worth offering for a kind, from its definition alone (never from
 * the data, so they are the same everywhere): how many per field for its
 * own fields of choices and yes/no fields, then per month for its first
 * date. One click adds one; nothing is on screen until a person does. */
export function recommendedCharts(usable: Usable[]): Chart[] {
  const own = usable.filter((u) => u.field.relation === 'self')
  const choices = own.filter((u) => {
    const listed = u.field.restrictions?.choices
    return (
      u.field.type === 'enum' ||
      u.field.type === 'boolean' ||
      (Array.isArray(listed) && listed.length > 0)
    )
  })
  const date = own.find((u) => u.type.grouping === 'bucket')
  const keys = [
    ...choices.map((u) => fieldKey(u.field)),
    ...(date ? [`${fieldKey(date.field)}:month`] : []),
  ]
  return keys.slice(0, RECOMMEND_UP_TO).map((key) => ({
    id: newChartId(),
    group_by: [key],
    measures: ['count'],
  }))
}
