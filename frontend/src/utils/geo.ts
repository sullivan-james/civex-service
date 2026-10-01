/**
 * Geographic values. Mirrors `civex/domain/geo.py`: a value is a GeoJSON
 * geometry (WGS84, longitude first). People type "latitude, longitude".
 */

import { parseCoordinates } from './geoCoords'

export interface Geometry {
  type: string
  coordinates: unknown
}

export const GEOMETRY_TYPES = [
  'Point',
  'MultiPoint',
  'LineString',
  'MultiLineString',
  'Polygon',
  'MultiPolygon',
] as const

const NUM = '[-+]?\\d+(?:\\.\\d+)?'
const WKT_POINT = new RegExp(
  `^\\s*POINT\\s*\\(\\s*(${NUM})\\s+(${NUM})\\s*\\)\\s*$`,
  'i',
)

export function isGeometry(value: unknown): value is Geometry {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as Geometry).type === 'string' &&
    (GEOMETRY_TYPES as readonly string[]).includes((value as Geometry).type) &&
    'coordinates' in value
  )
}

/** Read typed text as a location, or null. Point range is checked here;
 * the server checks everything else when the record is saved. */
export function parseLocation(text: string): Geometry | null {
  const trimmed = text.trim()
  const wkt = WKT_POINT.exec(trimmed)
  if (wkt) return point(parseFloat(wkt[1]), parseFloat(wkt[2]))
  if (trimmed.startsWith('{')) {
    try {
      const obj: unknown = JSON.parse(trimmed)
      return isGeometry(obj) ? obj : null
    } catch {
      return null
    }
  }
  const pair = parseCoordinates(trimmed)
  return pair ? point(pair[1], pair[0]) : null
}

function point(lon: number, lat: number): Geometry | null {
  if (Math.abs(lon) > 180 || Math.abs(lat) > 90) return null
  return { type: 'Point', coordinates: [lon, lat] }
}

/** Text for an input or a table cell: "56.12, -3.41" for a plain point,
 * a short description for other shapes. */
export function formatLocation(g: Geometry): string {
  const c = g.coordinates
  if (g.type === 'Point' && Array.isArray(c) && c.length >= 2) {
    const u = (g as unknown as { uncertainty_m?: unknown }).uncertainty_m
    const text = `${c[1]}, ${c[0]}`
    const parts = [
      c.length === 3 ? `${c[2]} m` : null,
      typeof u === 'number' ? `± ${u} m` : null,
    ].filter(Boolean)
    return parts.length ? `${text} (${parts.join(', ')})` : text
  }
  return g.type
}

/** The form-editable text for a stored value: only plain points round-trip
 * through the "lat, lon" input; anything else is kept as GeoJSON. */
export function editableText(g: Geometry): string {
  const c = g.coordinates
  if (g.type === 'Point' && Array.isArray(c) && c.length === 2)
    return `${c[1]}, ${c[0]}`
  return JSON.stringify(g)
}

/** Every [lon, lat] in a geometry, or null if it isn't shaped like one. */
export function positionsOf(g: Geometry): [number, number][] | null {
  const out: [number, number][] = []
  const walk = (c: unknown): boolean => {
    if (!Array.isArray(c) || c.length === 0) return false
    if (typeof c[0] === 'number') {
      if (c.length < 2 || typeof c[1] !== 'number') return false
      out.push([c[0], c[1]])
      return true
    }
    return c.every(walk)
  }
  return walk(g.coordinates) ? out : null
}

/** Is a position inside [west, south, east, north]? West > east means the
 * box crosses the 180th meridian. */
export function inBbox(
  lon: number,
  lat: number,
  [west, south, east, north]: number[],
): boolean {
  if (lat < south || lat > north) return false
  return west <= east ? lon >= west && lon <= east : lon >= west || lon <= east
}

/** Why a location breaks a field's shape / area rules, or null. Mirrors the
 * server's check (`domain/geo.py`) so people hear about it before saving. */
export function locationProblem(
  g: Geometry,
  rules: { geometry_types?: unknown; bbox?: unknown },
): string | null {
  const allowed = Array.isArray(rules.geometry_types)
    ? (rules.geometry_types as string[])
    : []
  if (allowed.length && !allowed.includes(g.type))
    return `This field takes ${allowed.join(' or ')}, not ${g.type}.`
  const box = rules.bbox
  if (Array.isArray(box) && box.length === 4) {
    const pts = positionsOf(g) ?? []
    const bad = pts.find(([lon, lat]) => !inBbox(lon, lat, box as number[]))
    if (bad)
      return `${bad[1]}, ${bad[0]} is outside the allowed area (${describeBbox(box as number[])}).`
  }
  return null
}

const hemi = (n: number, pos: string, neg: string) =>
  `${Math.abs(n)}° ${n >= 0 ? pos : neg}`

/** "48° N to 62° N, 12° W to 4° E" */
export function describeBbox([w, s, e, n]: number[]): string {
  return `${hemi(s, 'N', 'S')} to ${hemi(n, 'N', 'S')}, ${hemi(w, 'E', 'W')} to ${hemi(e, 'E', 'W')}`
}

/** "56.12° N, 3.41° W": how a point reads once the signs are spelled out. */
export function spokenPoint(g: Geometry): string | null {
  const c = g.coordinates
  if (g.type !== 'Point' || !Array.isArray(c) || c.length < 2) return null
  return `${hemi(c[1] as number, 'N', 'S')}, ${hemi(c[0] as number, 'E', 'W')}`
}

/** Well-known text for a geometry the editor can hold (longitude first). */
export function toWkt(g: Geometry): string {
  const p = (c: unknown) => (c as number[]).slice(0, 2).join(' ')
  const c = g.coordinates as number[][] | number[][][] | number[]
  if (g.type === 'Point') return `POINT(${p(c)})`
  if (g.type === 'LineString')
    return `LINESTRING(${(c as number[][]).map(p).join(', ')})`
  if (g.type === 'Polygon')
    return `POLYGON(${(c as number[][][]).map((r) => `(${r.map(p).join(', ')})`).join(', ')})`
  return JSON.stringify(g)
}
