import type { Geometry } from '../../utils/geo'
import { positionsOf } from '../../utils/geo'

/**
 * A small locator: an allowed area (optional) and where a location falls in
 * it. Plain latitude/longitude axes with a graticule, no basemap, so it
 * works offline and shows nothing it doesn't know. With no area it shows the
 * whole world; with one it zooms to the area, so "is my point inside?" is
 * visible at a glance.
 */
export function LocatorMap({
  bbox,
  location,
  className = '',
}: {
  /** [west, south, east, north]; west > east crosses the 180th meridian. */
  bbox?: number[] | null
  location?: Geometry | null
  className?: string
}) {
  const W = 360
  const H = 180
  const crosses = !!bbox && bbox[0] > bbox[2]
  // Work in a longitude range that doesn't jump at 180.
  const lonOf = (lon: number) => (crosses && lon < 0 ? lon + 360 : lon)
  const pts = location ? (positionsOf(location) ?? []) : []

  let west = -180
  let east = 180
  let south = -90
  let north = 90
  if (bbox) {
    const lons = [
      bbox[0],
      crosses ? bbox[2] + 360 : bbox[2],
      ...pts.map(([lon]) => lonOf(lon)),
    ]
    const lats = [bbox[1], bbox[3], ...pts.map(([, lat]) => lat)]
    west = Math.min(...lons)
    east = Math.max(...lons)
    south = Math.min(...lats)
    north = Math.max(...lats)
    const padX = Math.max((east - west) * 0.2, 0.5)
    const padY = Math.max((north - south) * 0.2, 0.5)
    west -= padX
    east += padX
    south -= padY
    north += padY
  }
  const sx = (lon: number) => ((lon - west) / (east - west)) * W
  const sy = (lat: number) => ((north - lat) / (north - south)) * H

  const step = (span: number) =>
    [30, 20, 10, 5, 2, 1, 0.5, 0.2, 0.1].find((s) => span / s >= 3) ?? 0.1
  const lines: number[][] = []
  const lonStep = step(east - west)
  const latStep = step(north - south)
  for (let x = Math.ceil(west / lonStep) * lonStep; x <= east; x += lonStep)
    lines.push([sx(x), 0, sx(x), H])
  for (let y = Math.ceil(south / latStep) * latStep; y <= north; y += latStep)
    lines.push([0, sy(y), W, sy(y)])

  const box = bbox
    ? {
        x: sx(bbox[0]),
        y: sy(bbox[3]),
        w: sx(crosses ? bbox[2] + 360 : bbox[2]) - sx(bbox[0]),
        h: sy(bbox[1]) - sy(bbox[3]),
      }
    : null

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={
        bbox
          ? 'Allowed area, with the entered location marked'
          : 'World map with the entered location marked'
      }
      className={`w-full rounded-md border border-border bg-canvas-subtle ${className}`}
    >
      {lines.map((l, i) => (
        <line
          key={i}
          x1={l[0]}
          y1={l[1]}
          x2={l[2]}
          y2={l[3]}
          className="stroke-border"
          strokeWidth={0.6}
        />
      ))}
      {box && (
        <rect
          x={box.x}
          y={box.y}
          width={box.w}
          height={box.h}
          className="fill-accent/15 stroke-accent"
          strokeWidth={1.2}
        />
      )}
      {location?.type === 'LineString' || location?.type === 'Polygon' ? (
        <polyline
          points={pts
            .map(([lon, lat]) => `${sx(lonOf(lon))},${sy(lat)}`)
            .join(' ')}
          fill="none"
          className="stroke-danger"
          strokeWidth={1.5}
        />
      ) : (
        pts.map(([lon, lat], i) => (
          <circle
            key={i}
            cx={sx(lonOf(lon))}
            cy={sy(lat)}
            r={4}
            className="fill-danger stroke-canvas"
            strokeWidth={1.5}
          />
        ))
      )}
    </svg>
  )
}
