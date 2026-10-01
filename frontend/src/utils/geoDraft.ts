import type { Geometry } from './geo'
import { normalizeLon } from './geoCoords'

/**
 * The geo editor works on a flat "draft" of one shape and turns it into
 * GeoJSON when applied. Only the shapes people can sensibly draw by hand are
 * editable: a point, a line, an area with one outer ring. Anything else a
 * field may hold (multi-part shapes, rings with holes) is shown but replaced
 * rather than edited.
 */

export type Shape = 'Point' | 'LineString' | 'Polygon'
export const SHAPES: Shape[] = ['Point', 'LineString', 'Polygon']

/** What a shape is called to a person. */
export const SHAPE_LABEL: Record<Shape, string> = {
  Point: 'Point',
  LineString: 'Line',
  Polygon: 'Area',
}

export type Position = [number, number] // [longitude, latitude]

export interface Draft {
  shape: Shape
  /** Points of the shape. For an area, the ring without its closing repeat. */
  positions: Position[]
  /** Point only: height above sea level in metres, negative below (a depth). */
  elevation: number | null
  /** Point only: how well the position is known, in metres. */
  uncertainty: number | null
}

export function emptyDraft(shape: Shape): Draft {
  return { shape, positions: [], elevation: null, uncertainty: null }
}

/** Shapes a field accepts that the editor can draw. */
export function editableShapes(rules: { geometry_types?: unknown }): Shape[] {
  const allowed = Array.isArray(rules.geometry_types)
    ? (rules.geometry_types as string[])
    : []
  if (allowed.length === 0) return SHAPES
  return SHAPES.filter((s) => allowed.includes(s))
}

const pos = (p: unknown): Position | null =>
  Array.isArray(p) && typeof p[0] === 'number' && typeof p[1] === 'number'
    ? [p[0], p[1]]
    : null

/** A draft from stored GeoJSON, or why the editor can't edit it. */
export function draftFromGeometry(
  g: Geometry | null,
  fallback: Shape,
): { draft: Draft; unsupported: string | null } {
  if (!g) return { draft: emptyDraft(fallback), unsupported: null }
  const c = g.coordinates
  const extras = g as unknown as { uncertainty_m?: unknown }
  if (g.type === 'Point' && Array.isArray(c)) {
    const p = pos(c)
    return {
      draft: {
        shape: 'Point',
        positions: p ? [p] : [],
        elevation: typeof c[2] === 'number' ? c[2] : null,
        uncertainty:
          typeof extras.uncertainty_m === 'number'
            ? extras.uncertainty_m
            : null,
      },
      unsupported: null,
    }
  }
  if (g.type === 'LineString' && Array.isArray(c)) {
    return {
      draft: {
        ...emptyDraft('LineString'),
        positions: c.map(pos).filter((p): p is Position => !!p),
      },
      unsupported: null,
    }
  }
  if (g.type === 'Polygon' && Array.isArray(c)) {
    if (c.length !== 1)
      return {
        draft: emptyDraft(fallback),
        unsupported:
          'This area has holes, which the editor can’t change. Draw a new one to replace it.',
      }
    const ring = (c[0] as unknown[]).map(pos).filter((p): p is Position => !!p)
    return {
      draft: { ...emptyDraft('Polygon'), positions: ring.slice(0, -1) },
      unsupported: null,
    }
  }
  return {
    draft: emptyDraft(fallback),
    unsupported: `The editor can’t change a ${g.type}. Draw or import a new shape to replace it.`,
  }
}

/** GeoJSON for a draft, or what is missing. Longitudes are wrapped to -180..180. */
export function geometryFromDraft(d: Draft): {
  geometry: Geometry | null
  problem: string | null
} {
  const ps = d.positions.map(
    ([lon, lat]) => [normalizeLon(lon), lat] as Position,
  )
  if (d.shape === 'Point') {
    if (ps.length === 0) return { geometry: null, problem: null }
    const coords: number[] = [...ps[0]]
    if (d.elevation !== null) coords.push(d.elevation)
    const g: Geometry & { uncertainty_m?: number } = {
      type: 'Point',
      coordinates: coords,
    }
    if (d.uncertainty !== null) g.uncertainty_m = d.uncertainty
    return { geometry: g, problem: null }
  }
  if (d.shape === 'LineString') {
    if (ps.length === 0) return { geometry: null, problem: null }
    if (ps.length < 2)
      return { geometry: null, problem: 'A line needs at least 2 points.' }
    return { geometry: { type: 'LineString', coordinates: ps }, problem: null }
  }
  if (ps.length === 0) return { geometry: null, problem: null }
  if (ps.length < 3)
    return { geometry: null, problem: 'An area needs at least 3 corners.' }
  return {
    geometry: { type: 'Polygon', coordinates: [[...ps, ps[0]]] },
    problem: null,
  }
}

/** Plain-language one-liner for a stored location: "Line, 214 points". */
export function describeGeometry(g: Geometry): string {
  const c = g.coordinates
  if (g.type === 'LineString' && Array.isArray(c))
    return `Line, ${c.length} points`
  if (g.type === 'Polygon' && Array.isArray(c) && Array.isArray(c[0]))
    return `Area, ${(c[0] as unknown[]).length - 1} corners`
  return g.type
}
