/**
 * Charts: the one definition (`api/schemas.Chart`, civex/domain/charts.py)
 * as the app writes, names and suggests it. A chart is bars (one bar for
 * each value of a field, each bar showing a count or a number worked out) or
 * a map. Pure: titles in plain words, what the "New chart" panel offers, the
 * address form of a list's unsaved charts, and the charts suggested for a
 * kind that has none set.
 */

import type { Chart, FieldTypeDescriptor, Schema } from '../api/schemas'
import type { RecordSummary } from '../api/records'
import type { FilterableField } from './hierarchy'
import { displayLabel } from './naming'
import { fieldKey, splitGroupKey } from './summary'

/** Past this many listed records, charts wait for a click. */
export const CHARTS_AUTO_UP_TO = 200_000
/** A field is suggested as a chart when the listed records hold between
 * this many different values of it. */
export const SUGGEST_MIN = 2
export const SUGGEST_MAX = 20
/** How many fields the suggestions look at, and how many charts they make. */
export const SUGGEST_LOOK_AT = 8
export const SUGGEST_CHARTS = 3
/** A date is charted by year once its values span more than this many years. */
const YEARS_BY_MONTH = 3

export function newChartId(): string {
  return Math.random().toString(36).slice(2, 10)
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
/** The chart opened large. */
export const OPEN_CHART_PARAM = 'chart'

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

// --- suggestions, chosen from the data

/** The fields worth looking at for a suggestion, shown columns first, own
 * fields before those of a kind above: at most SUGGEST_LOOK_AT. */
export function suggestionCandidates(
  usable: Usable[],
  shown: string[],
): Usable[] {
  const rank = (u: Usable) =>
    (shown.includes(u.field.name) && u.field.relation === 'self' ? 0 : 2) +
    (u.field.relation === 'self' ? 0 : 1)
  return usable
    .filter((u) => u.type.grouping && u.type.grouping !== 'each')
    .filter(
      (u) => u.type.measures.includes('distinct') || u.field.type === 'boolean',
    )
    .map((u, i) => ({ u, i }))
    .sort((a, b) => rank(a.u) - rank(b.u) || a.i - b.i)
    .slice(0, SUGGEST_LOOK_AT)
    .map((x) => x.u)
}

/** What to ask the summary so the suggestions can be chosen: how many
 * different values each candidate holds, and a date's first and last. */
export function suggestionMeasures(candidates: Usable[]): string[] {
  return candidates.flatMap((u) => {
    const key = fieldKey(u.field)
    if (u.type.grouping === 'bucket')
      return [`distinct:${key}`, `min:${key}`, `max:${key}`]
    return u.type.measures.includes('distinct') ? [`distinct:${key}`] : []
  })
}

/** The charts suggested for a list whose kind has none set: one per field
 * the listed records hold a handful of different values of (dates by month,
 * or by year over a long span), then a map where there is a location. */
export function suggestCharts(
  candidates: Usable[],
  answer: RecordSummary | undefined,
  geo: FilterableField | undefined,
): Chart[] {
  const total = new Map<string, unknown>()
  answer?.measure_columns.forEach((c, i) => total.set(c.key, answer.total[i]))
  const charts: Chart[] = []
  for (const u of candidates) {
    if (charts.length >= SUGGEST_CHARTS) break
    const key = fieldKey(u.field)
    const different = Number(total.get(`distinct:${key}`) ?? 0)
    if (u.type.grouping === 'bucket') {
      if (different < SUGGEST_MIN) continue
      const first = String(total.get(`min:${key}`) ?? '').slice(0, 4)
      const last = String(total.get(`max:${key}`) ?? '').slice(0, 4)
      const years = Number(last) - Number(first)
      const how = years > YEARS_BY_MONTH ? 'year' : 'month'
      charts.push({
        id: `s-${key}`,
        group_by: [`${key}:${how}`],
        measures: ['count'],
      })
      continue
    }
    const few =
      u.field.type === 'boolean'
        ? !!answer
        : different >= SUGGEST_MIN && different <= SUGGEST_MAX
    if (few)
      charts.push({ id: `s-${key}`, group_by: [key], measures: ['count'] })
  }
  if (geo)
    charts.push({
      id: `s-map-${fieldKey(geo)}`,
      map: fieldKey(geo),
      group_by: [],
      measures: [],
    })
  return charts
}
