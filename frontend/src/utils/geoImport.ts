import type { Geometry } from './geo'
import { isGeometry } from './geo'

/**
 * Reading locations out of the files people already have: GeoJSON, GPX
 * (a GPS unit's track or waypoints), KML (Google Earth) and WKT text. Each
 * file can hold many things; the caller picks one. OpenLayers' readers are
 * loaded on demand, so none of this is in the main bundle.
 */

export interface Candidate {
  /** What to show in the list, e.g. "Track 1 (4,318 points)". */
  label: string
  geometry: Geometry
}

export const IMPORT_ACCEPT = '.geojson,.json,.gpx,.kml,.wkt,.txt'

const count = (g: Geometry): number => {
  const walk = (c: unknown): number =>
    Array.isArray(c)
      ? typeof c[0] === 'number'
        ? 1
        : c.reduce<number>((n, x) => n + walk(x), 0)
      : 0
  return walk(g.coordinates)
}

function describe(
  name: string | undefined,
  g: Geometry,
  fallback: string,
): string {
  const what =
    g.type === 'Point' ? '' : ` (${count(g).toLocaleString()} points)`
  return `${name?.trim() || fallback}${what}`
}

/** Flatten any GeoJSON object into plain geometries. */
function geometriesOf(
  obj: unknown,
  name?: string,
): { name?: string; g: Geometry }[] {
  if (!obj || typeof obj !== 'object') return []
  const o = obj as Record<string, unknown>
  if (o.type === 'FeatureCollection' && Array.isArray(o.features))
    return o.features.flatMap((f) => geometriesOf(f))
  if (o.type === 'Feature') {
    const props = (o.properties ?? {}) as Record<string, unknown>
    const n = typeof props.name === 'string' ? props.name : name
    return geometriesOf(o.geometry, n)
  }
  if (o.type === 'GeometryCollection' && Array.isArray(o.geometries))
    return o.geometries.flatMap((g) => geometriesOf(g, name))
  return isGeometry(obj) ? [{ name, g: obj }] : []
}

/** MultiLineString (a GPX track with segments) becomes one LineString: for a
 * track, the segments are one journey. */
function simplify(g: Geometry): Geometry {
  if (g.type === 'MultiLineString' && Array.isArray(g.coordinates))
    return {
      type: 'LineString',
      coordinates: (g.coordinates as number[][][]).flat(),
    }
  return g
}

/** A file's text. `Blob.text()` where it exists, else a FileReader. */
export function readFileText(file: File): Promise<string> {
  if (typeof file.text === 'function') return file.text()
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsText(file)
  })
}

export async function readLocations(
  text: string,
  filename: string,
): Promise<Candidate[]> {
  const lower = filename.toLowerCase()
  const trimmed = text.trim()
  let found: { name?: string; g: Geometry }[]

  if (
    trimmed.startsWith('{') ||
    lower.endsWith('.geojson') ||
    lower.endsWith('.json')
  ) {
    found = geometriesOf(JSON.parse(trimmed))
  } else if (
    lower.endsWith('.gpx') ||
    lower.endsWith('.kml') ||
    trimmed.startsWith('<')
  ) {
    const isGpx = lower.endsWith('.gpx') || /<gpx[\s>]/i.test(trimmed)
    const [{ default: GeoJSON }, format] = await Promise.all([
      import('ol/format/GeoJSON'),
      isGpx ? import('ol/format/GPX') : import('ol/format/KML'),
    ])
    const reader = new format.default()
    const features = reader.readFeatures(trimmed, {
      dataProjection: 'EPSG:4326',
      featureProjection: 'EPSG:4326',
    })
    const collection = new GeoJSON().writeFeaturesObject(features)
    found = geometriesOf(collection)
  } else {
    const { default: WKT } = await import('ol/format/WKT')
    const feature = new WKT().readFeature(trimmed, {
      dataProjection: 'EPSG:4326',
      featureProjection: 'EPSG:4326',
    })
    const { default: GeoJSON } = await import('ol/format/GeoJSON')
    found = geometriesOf(new GeoJSON().writeFeatureObject(feature))
  }

  return (
    found
      .map(({ name, g }, i) => {
        const geometry = simplify(g)
        return {
          label: describe(name, geometry, `${geometry.type} ${i + 1}`),
          geometry,
        }
      })
      // Anything the editor can't hold as a field value is dropped from the list.
      .filter(({ geometry }) => count(geometry) > 0)
  )
}
