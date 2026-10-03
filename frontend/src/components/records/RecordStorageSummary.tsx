import { Link } from 'react-router'
import type { FileRef } from '../../api/files'
import { useUISettings } from '../../hooks/useUISettings'
import { AlertTriangle, HardDrive } from '../ui/icons'

/** Every file reference in a record's data (file and file_list values). */
function filesIn(data: Record<string, unknown>): FileRef[] {
  const isFile = (v: unknown): v is FileRef =>
    typeof v === 'object' &&
    v !== null &&
    typeof (v as { sha256?: unknown }).sha256 === 'string'
  return Object.values(data).flatMap((value) =>
    Array.isArray(value) ? value.filter(isFile) : isFile(value) ? [value] : [],
  )
}

/** Where a record's files are, as a whole: how many on each volume. Shown when
 * the files are split across volumes or any can't be opened right now (the two
 * things worth noticing about a record), and always in advanced mode. */
export function RecordStorageSummary({
  data,
}: {
  data: Record<string, unknown>
}) {
  const { data: ui } = useUISettings()
  const files = filesIn(data)
  if (files.length === 0) return null

  const perVolume = new Map<string, number>()
  for (const file of files) {
    const volume = file.location?.volume ?? 'unknown'
    perVolume.set(volume, (perVolume.get(volume) ?? 0) + 1)
  }
  const unavailable = files.filter(
    (f) => f.location?.available === false,
  ).length
  const split = perVolume.size > 1
  if (!(ui?.show_advanced || split || unavailable > 0)) return null

  const where = [...perVolume.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([volume, n]) => `${volume} (${n})`)
    .join(', ')

  return (
    <div
      aria-label="Where this record's files are stored"
      role="group"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-border bg-canvas-subtle px-3 py-2 text-xs text-fg-muted"
    >
      <span className="inline-flex items-center gap-1.5">
        <HardDrive size={13} aria-hidden="true" />
        {files.length} {files.length === 1 ? 'file' : 'files'} stored on {where}
      </span>
      {split && (
        <span className="text-attention">
          Split across {perVolume.size} volumes
        </span>
      )}
      {unavailable > 0 && (
        <span className="inline-flex items-center gap-1 text-attention">
          <AlertTriangle size={12} aria-hidden="true" />
          {unavailable} not available right now
        </span>
      )}
      <Link
        to="/settings/storage"
        className="ml-auto text-accent hover:underline"
      >
        Storage settings
      </Link>
    </div>
  )
}
