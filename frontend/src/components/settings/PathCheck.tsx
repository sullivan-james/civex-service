import type { PathInspection } from '../../api/store'
import { Badge } from '../ui'
import { AlertTriangle, Check, Loader2 } from '../ui/icons'
import { errorMessage } from '../../lib/errors'
import { formatSize } from '../../utils/storage'

/** Where a folder sits: what kind of storage it is. */
function kindLabel(i: PathInspection): string {
  if (i.is_network) return 'Network drive'
  if (i.same_disk_as_project === true) return 'Same disk as the project'
  if (i.same_disk_as_project === false) return 'Separate drive'
  return 'Local folder'
}

/** A live check of the folder being chosen for a volume: what it is, how much
 * room it has, and anything that blocks adding it or deserves a warning. The
 * server decides all of this, using the rules adding a volume enforces. */
export function PathCheck({
  inspection,
  checking,
  error,
}: {
  inspection: PathInspection | undefined
  checking: boolean
  error: unknown
}) {
  if (error)
    return (
      <p role="alert" className="text-xs text-danger">
        Couldn&apos;t check this location: {errorMessage(error)}
      </p>
    )
  if (!inspection)
    return checking ? (
      <p className="flex items-center gap-1.5 text-xs text-fg-muted">
        <Loader2 size={13} className="animate-spin" /> Checking this location…
      </p>
    ) : null

  const used =
    inspection.total_bytes && inspection.free_bytes != null
      ? Math.round(
          ((inspection.total_bytes - inspection.free_bytes) /
            inspection.total_bytes) *
            100,
        )
      : null

  return (
    <div
      aria-label="Location check"
      className={`rounded-md border border-border bg-canvas-subtle px-3 py-2.5 space-y-2 text-xs ${checking ? 'opacity-60' : ''}`}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant={inspection.is_network ? 'accent' : 'default'}>
          {kindLabel(inspection)}
        </Badge>
        <Badge>
          {inspection.will_create ? 'New folder' : 'Existing folder'}
        </Badge>
        {inspection.has_civex_data && (
          <Badge variant="success">Holds Civex files</Badge>
        )}
      </div>

      {used !== null && (
        <div>
          <div
            role="img"
            aria-label={`${used}% of the disk is used`}
            className="h-1.5 rounded-full bg-border overflow-hidden"
          >
            <div className="h-full bg-accent" style={{ width: `${used}%` }} />
          </div>
          <p className="mt-1 text-fg-muted">
            {formatSize(inspection.free_bytes)} free of{' '}
            {formatSize(inspection.total_bytes)}
          </p>
        </div>
      )}

      {inspection.problems.map((p) => (
        <p
          key={p}
          role="alert"
          className="flex items-start gap-1.5 text-danger"
        >
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          {p}
        </p>
      ))}
      {inspection.warnings.map((w) => (
        <p key={w} className="flex items-start gap-1.5 text-attention">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          {w}
        </p>
      ))}
      {inspection.problems.length === 0 && (
        <p className="flex items-center gap-1.5 text-success">
          <Check size={13} /> Ready to add
        </p>
      )}
    </div>
  )
}
