import type { CollectionStorageReport } from '../api/store'

/** Where to gather a collection's files, and how many are elsewhere: onto its
 * home volume if it has one, otherwise where most of it already is. `null`
 * when there is nothing to gather. The one rule behind every "Gather" button. */
export function gatherPlan(
  report: CollectionStorageReport,
  home?: string,
): { target: string; elsewhere: number } | null {
  const target = home ?? report.volumes[0]?.volume
  if (!target) return null
  const elsewhere = report.volumes
    .filter((v) => v.volume !== target)
    .reduce((n, v) => n + v.files, 0)
  return elsewhere > 0 ? { target, elsewhere } : null
}
