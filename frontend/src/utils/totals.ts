/**
 * The totals under a list: for every record listed (not just the page), the
 * average, smallest and largest of each number column and how many different
 * values each choice column holds. One summary with no grouping
 * (`POST /records/summary`), asked after the rows.
 */

import type { RecordSummary } from '../api/records'
import type { Field } from '../api/schemas'
import { formatSummaryValue } from './summary'

const isNumber = (f: Field) => f.type === 'integer' || f.type === 'float'
const isChoice = (f: Field) =>
  f.type === 'enum' ||
  f.type === 'boolean' ||
  (Array.isArray(f.restrictions?.choices) && f.restrictions.choices.length > 0)

/** What to ask for the shown columns that are the kind's own fields. */
export function totalsMeasures(columns: string[], fields: Field[]): string[] {
  return columns.flatMap((name) => {
    const f = fields.find((x) => x.name === name)
    if (!f) return []
    if (isNumber(f)) return [`mean:${name}`, `min:${name}`, `max:${name}`]
    if (isChoice(f)) return [`distinct:${name}`]
    return []
  })
}

/** Each column's total, as its cell reads: "avg 12.4 · 2 to 40", "4 different". */
export function totalsCells(
  columns: string[],
  summary: RecordSummary | undefined,
): Record<string, string> {
  if (!summary) return {}
  const got = new Map<string, unknown>()
  summary.measure_columns.forEach((c, i) => got.set(c.key, summary.total[i]))
  const cells: Record<string, string> = {}
  for (const name of columns) {
    const mean = got.get(`mean:${name}`)
    const different = got.get(`distinct:${name}`)
    if (typeof mean === 'number')
      cells[name] =
        `avg ${formatSummaryValue(mean)} · ${formatSummaryValue(got.get(`min:${name}`))} to ${formatSummaryValue(got.get(`max:${name}`))}`
    else if (typeof different === 'number')
      cells[name] = `${different} different`
  }
  return cells
}
