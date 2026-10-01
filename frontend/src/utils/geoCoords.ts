/**
 * Reading and writing latitude/longitude the ways people use them. The
 * reader mirrors `parse_coordinates` in `civex/domain/geo.py`; both are
 * tested against the same table of examples, so what the CLI and a CSV
 * import accept is what the browser accepts.
 */

export type CoordFormat = 'dd' | 'ddm' | 'dms'

export const COORD_FORMATS: {
  key: CoordFormat
  label: string
  example: string
}[] = [
  { key: 'dd', label: 'Decimal degrees', example: '56.1200° N' },
  {
    key: 'ddm',
    label: 'Degrees and decimal minutes',
    example: '56° 07.200′ N',
  },
  { key: 'dms', label: 'Degrees, minutes, seconds', example: '56° 07′ 12″ N' },
]

const HEMI_SIGN: Record<string, number> = { N: 1, E: 1, S: -1, W: -1 }
const NUM = '[-+]?\\d+(?:\\.\\d+)?'
const UNSIGNED = /\d+(?:\.\d+)?/g
const LATLON = new RegExp(`^\\s*(${NUM})\\s*[, ]\\s*(${NUM})\\s*$`)

function sexagesimal(numbers: string[]): number | null {
  if (numbers.length < 1 || numbers.length > 3) return null
  const parts = numbers.map(parseFloat)
  if (parts.slice(1).some((p) => p >= 60)) return null
  return parts.reduce((sum, p, i) => sum + p / 60 ** i, 0)
}

/** [latitude, longitude] from text, or null. Ranges are the caller's to check. */
export function parseCoordinates(text: string): [number, number] | null {
  const s = text
    .replace(/[′’`]/g, "'")
    .replace(/[″”]/g, '"')
    .replace(/''/g, '"')
    .replace(/[º˚]/g, '°')
    .replace(/[,;]/g, ' ')
    .trim()
  const hemis: number[] = []
  for (let i = 0; i < s.length; i++)
    if (s[i].toUpperCase() in HEMI_SIGN) hemis.push(i)

  const segments: { axis: 'lat' | 'lon'; sign: number; body: string }[] = []
  if (hemis.length === 2) {
    const bodies: [string, string][] =
      hemis[0] === 0
        ? [
            [s[hemis[0]], s.slice(hemis[0] + 1, hemis[1])],
            [s[hemis[1]], s.slice(hemis[1] + 1)],
          ]
        : [
            [s[hemis[0]], s.slice(0, hemis[0])],
            [s[hemis[1]], s.slice(hemis[0] + 1, hemis[1])],
          ]
    for (const [letter, body] of bodies) {
      if (body.includes('-')) return null // a sign and a hemisphere together
      const l = letter.toUpperCase()
      segments.push({
        axis: 'NS'.includes(l) ? 'lat' : 'lon',
        sign: HEMI_SIGN[l],
        body,
      })
    }
    if (segments[0].axis === segments[1].axis) return null
  } else if (hemis.length === 0) {
    if (/[°'"]/.test(s)) {
      const parts = s.split(new RegExp(`\\s+(?=${NUM}\\s*°)`))
      if (parts.length !== 2) return null
      parts.forEach((part, i) =>
        segments.push({
          axis: i === 0 ? 'lat' : 'lon',
          sign: part.trimStart().startsWith('-') ? -1 : 1,
          body: part,
        }),
      )
    } else {
      const m = LATLON.exec(s)
      return m ? [parseFloat(m[1]), parseFloat(m[2])] : null
    }
  } else {
    return null
  }
  const values: Record<string, number> = {}
  for (const { axis, sign, body } of segments) {
    const v = sexagesimal(body.match(UNSIGNED) ?? [])
    if (v === null) return null
    values[axis] = sign * v
  }
  return [values.lat, values.lon]
}

/** Wrap a longitude into -180..180. */
export function normalizeLon(lon: number): number {
  if (lon >= -180 && lon <= 180) return lon // untouched: no float noise
  return ((((lon + 180) % 360) + 360) % 360) - 180
}

export interface Dms {
  negative: boolean
  degrees: number
  minutes: number
  seconds: number
}

/** Split a signed degree value into degrees, minutes and seconds. */
export function toDms(value: number): Dms {
  const abs = Math.abs(value)
  let degrees = Math.floor(abs)
  let minutes = Math.floor((abs - degrees) * 60)
  let seconds = (((abs - degrees) * 60 - minutes) * 3600) / 60
  // Rounding 59.9999 seconds up must carry, not print 60.
  seconds = Math.round(seconds * 1e4) / 1e4
  if (seconds >= 60) {
    seconds -= 60
    minutes += 1
  }
  if (minutes >= 60) {
    minutes -= 60
    degrees += 1
  }
  return { negative: value < 0, degrees, minutes, seconds }
}

export function fromDms({ negative, degrees, minutes, seconds }: Dms): number {
  const v = degrees + minutes / 60 + seconds / 3600
  return negative ? -v : v
}

/** One coordinate as text: "56.1200° N", "56° 07.200′ N", "56° 07′ 12.00″ N". */
export function formatCoordinate(
  value: number,
  axis: 'lat' | 'lon',
  format: CoordFormat,
): string {
  const hemi = axis === 'lat' ? (value < 0 ? 'S' : 'N') : value < 0 ? 'W' : 'E'
  const abs = Math.abs(value)
  if (format === 'dd') return `${trim(abs, 6)}° ${hemi}`
  const d = toDms(value)
  if (format === 'ddm')
    return `${d.degrees}° ${trim(d.minutes + d.seconds / 60, 4)}′ ${hemi}`
  return `${d.degrees}° ${d.minutes}′ ${trim(d.seconds, 2)}″ ${hemi}`
}

function trim(n: number, places: number): string {
  return n.toFixed(places).replace(/\.?0+$/, '') || '0'
}
