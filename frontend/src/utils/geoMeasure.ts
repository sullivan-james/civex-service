/** Sizes of drawn lines and areas, so a researcher can sanity-check a shape
 * ("a 4 m² plot?") without leaving the form. Spherical approximations. */

const R = 6371008.8 // mean Earth radius, metres
const rad = (d: number) => (d * Math.PI) / 180

/** Great-circle distance in metres between [lon, lat] positions. */
export function distanceMeters(a: number[], b: number[]): number {
  const dLat = rad(b[1] - a[1])
  const dLon = rad(b[0] - a[0])
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)))
}

export function lineLengthMeters(positions: number[][]): number {
  let total = 0
  for (let i = 1; i < positions.length; i++)
    total += distanceMeters(positions[i - 1], positions[i])
  return total
}

/** Area in square metres of a ring of [lon, lat] (closed or open). */
export function ringAreaSqMeters(ring: number[][]): number {
  const pts =
    ring.length > 1 && same(ring[0], ring[ring.length - 1])
      ? ring.slice(0, -1)
      : ring
  if (pts.length < 3) return 0
  let sum = 0
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i]
    const q = pts[(i + 1) % pts.length]
    let dLon = rad(q[0] - p[0])
    if (dLon > Math.PI) dLon -= 2 * Math.PI
    if (dLon < -Math.PI) dLon += 2 * Math.PI
    sum += dLon * (2 + Math.sin(rad(p[1])) + Math.sin(rad(q[1])))
  }
  return Math.abs((sum * R * R) / 2)
}

const same = (a: number[], b: number[]) => a[0] === b[0] && a[1] === b[1]

export function formatLength(m: number): string {
  if (m < 1000) return `${m < 10 ? m.toFixed(1) : Math.round(m)} m`
  return `${(m / 1000).toFixed(m < 10000 ? 2 : 1)} km`
}

export function formatArea(sqm: number): string {
  if (sqm < 10_000) return `${sqm < 100 ? sqm.toFixed(1) : Math.round(sqm)} m²`
  if (sqm < 1_000_000) return `${(sqm / 10_000).toFixed(2)} ha`
  return `${(sqm / 1_000_000).toFixed(sqm < 1e8 ? 2 : 1)} km²`
}
