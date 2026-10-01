/**
 * Partial dates: a year, a month or a day. Mirrors
 * `civex/domain/partial_dates.py`. A `date` field's `precision` restriction
 * names the least precise form it accepts.
 */

export const PRECISIONS = ['year', 'month', 'day'] as const
export type Precision = (typeof PRECISIONS)[number]

const PATTERNS: Record<Precision, RegExp> = {
  year: /^\d{4}$/,
  month: /^\d{4}-\d{2}$/,
  day: /^\d{4}-\d{2}-\d{2}$/,
}

export function precisionOf(value: string): Precision | null {
  const text = value.trim()
  return PRECISIONS.find((p) => PATTERNS[p].test(text)) ?? null
}

/** True when the text is a real year, month or day (no 2023-02-30). */
export function isValidPartialDate(value: string): boolean {
  const text = value.trim()
  const kind = precisionOf(text)
  if (!kind) return false
  const year = parseInt(text.slice(0, 4), 10)
  if (year < 1) return false
  if (kind === 'year') return true
  const month = parseInt(text.slice(5, 7), 10)
  if (month < 1 || month > 12) return false
  if (kind === 'month') return true
  const day = parseInt(text.slice(8, 10), 10)
  return day >= 1 && day <= new Date(Date.UTC(year, month, 0)).getUTCDate()
}

export function atLeast(value: string, least: Precision): boolean {
  const kind = precisionOf(value)
  return !!kind && PRECISIONS.indexOf(kind) >= PRECISIONS.indexOf(least)
}

export function precisionHelp(least: Precision): string {
  return {
    year: 'A year, a month or a full date all work.',
    month: 'A month or a full date works; a bare year does not.',
    day: 'A full date is needed.',
  }[least]
}

export function placeholderFor(least: Precision): string {
  return {
    year: '2019, 2019-06 or 2019-06-14',
    month: '2019-06 or 2019-06-14',
    day: '2019-06-14',
  }[least]
}
