import { useVolumes } from './useStore'

export const PROJECT = 'project'

/** The drives a selection's files can be put on, and what the chosen one has
 * free. One component for both ways of putting files on one drive (moving them,
 * copying them), so the choices and the "will it fit" rule are the same. */
export function useDriveChoice({
  holding,
  need,
  allowProject,
  chosen,
}: {
  /** The drive that already holds most of the files: suggested first. */
  holding?: string
  /** Bytes that would land on the drive. */
  need: number
  /** The project folder is a place to copy to, not to move into. */
  allowProject: boolean
  chosen: string | null
}) {
  const { data: volumes = [] } = useVolumes()
  const targets = volumes.filter((v) => v.available && v.state === 'online')
  const fallback = allowProject ? PROJECT : (targets[0]?.name ?? '')
  const target =
    chosen ??
    (holding && targets.some((v) => v.name === holding) ? holding : fallback)
  const free =
    target === PROJECT
      ? null
      : (targets.find((v) => v.name === target)?.disk_free_bytes ?? null)
  return { targets, target, free, tooBig: free != null && need > free }
}
