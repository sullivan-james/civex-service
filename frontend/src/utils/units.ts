/**
 * Unit conversion for numeric fields. Mirrors `civex/domain/units.py` (the
 * Python table is the authority; keep the two in step). A field has one unit
 * and every stored value is in it: this only runs where data enters, so that
 * typing "1024 ft" into a metres field stores 312.1152, never 1024.
 */

interface UnitDef {
  dimension: string
  factor: number
  offset?: number
}

// value in the dimension's base unit = value * factor + offset
const UNITS: Record<string, UnitDef> = {
  m: { dimension: 'length', factor: 1 },
  mm: { dimension: 'length', factor: 0.001 },
  cm: { dimension: 'length', factor: 0.01 },
  km: { dimension: 'length', factor: 1000 },
  in: { dimension: 'length', factor: 0.0254 },
  ft: { dimension: 'length', factor: 0.3048 },
  fathom: { dimension: 'length', factor: 1.8288 },
  nmi: { dimension: 'length', factor: 1852 },
  '°C': { dimension: 'temperature', factor: 1 },
  K: { dimension: 'temperature', factor: 1, offset: -273.15 },
  '°F': { dimension: 'temperature', factor: 5 / 9, offset: -160 / 9 },
  dbar: { dimension: 'pressure', factor: 1 },
  Pa: { dimension: 'pressure', factor: 0.0001 },
  hPa: { dimension: 'pressure', factor: 0.01 },
  kPa: { dimension: 'pressure', factor: 0.1 },
  bar: { dimension: 'pressure', factor: 10 },
  s: { dimension: 'time', factor: 1 },
  min: { dimension: 'time', factor: 60 },
  h: { dimension: 'time', factor: 3600 },
  d: { dimension: 'time', factor: 86400 },
  'm/s': { dimension: 'speed', factor: 1 },
  'km/h': { dimension: 'speed', factor: 1000 / 3600 },
  kn: { dimension: 'speed', factor: 1852 / 3600 },
  g: { dimension: 'mass', factor: 0.001 },
  kg: { dimension: 'mass', factor: 1 },
  lb: { dimension: 'mass', factor: 0.45359237 },
}

const ALIASES: Record<string, string> = {
  degC: '°C',
  C: '°C',
  degF: '°F',
  F: '°F',
  knot: 'kn',
  knots: 'kn',
}

/** Convertible unit symbols, grouped by what they measure (for pickers). */
export const UNIT_GROUPS: Record<string, string[]> = Object.entries(
  UNITS,
).reduce<Record<string, string[]>>((groups, [symbol, def]) => {
  ;(groups[def.dimension] ??= []).push(symbol)
  return groups
}, {})

export function canonicalUnit(symbol: string): string {
  const s = symbol.trim()
  return ALIASES[s] ?? s
}

export function dimensionOf(symbol: string): string | null {
  return UNITS[canonicalUnit(symbol)]?.dimension ?? null
}

/** Convert, or an Error message string when the two units don't convert. */
export function convert(
  value: number,
  from: string,
  to: string,
): { value: number } | { error: string } {
  const src = canonicalUnit(from)
  const dst = canonicalUnit(to)
  if (src === dst) return { value }
  const a = UNITS[src]
  const b = UNITS[dst]
  if (!a || !b) {
    return {
      error: `Can't convert ${from} to ${to}: '${a ? to : from}' is not a convertible unit`,
    }
  }
  if (a.dimension !== b.dimension) {
    return {
      error: `Can't convert ${from} (${a.dimension}) to ${to} (${b.dimension})`,
    }
  }
  const base = value * a.factor + (a.offset ?? 0)
  return { value: (base - (b.offset ?? 0)) / b.factor }
}

const QUANTITY =
  /^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(\S.*?)?\s*$/

/** "1024 ft" -> {value: 1024, unit: 'ft'}; a bare number has no unit. */
export function parseQuantity(
  text: string,
): { value: number; unit: string | null } | null {
  const m = QUANTITY.exec(text)
  if (!m) return null
  return { value: parseFloat(m[1]), unit: m[2] ? canonicalUnit(m[2]) : null }
}

/**
 * Read typed or pasted text for a field stored in `fieldUnit`. A bare number
 * is taken to already be in that unit; "1024 ft" is converted. A unit typed
 * into a field that has none is an error rather than silently dropped.
 */
export function toFieldUnit(
  text: string,
  fieldUnit: string | null,
): { value: number } | { error: string } {
  const q = parseQuantity(text)
  if (!q) return { error: `"${text}" is not a number` }
  if (q.unit === null) return { value: q.value }
  if (fieldUnit === null)
    return { error: `This field has no unit; enter just the number` }
  return convert(q.value, q.unit, fieldUnit)
}

/** An example of typing a value with a unit other than `unit`, for hints:
 * "1024 ft" for a metres field. */
export function exampleWithUnit(unit: string): string {
  const alt: Record<string, string> = {
    length: unit === 'ft' ? '100 m' : '1024 ft',
    temperature: unit === '°F' ? '20 °C' : '68 °F',
    pressure: unit === 'hPa' ? '10 dbar' : '1013 hPa',
    time: unit === 'min' ? '90 s' : '90 min',
    speed: unit === 'kn' ? '5 m/s' : '10 kn',
    mass: unit === 'lb' ? '2 kg' : '4 lb',
  }
  const dim = dimensionOf(unit)
  return dim ? alt[dim] : `5 ${unit}`
}

/** Round away binary noise from a conversion for display in an input. */
export function tidy(n: number): string {
  return String(parseFloat(n.toPrecision(12)))
}
