import GCPanel from '../GCPanel'

/** Housekeeping for stored files. */
export function MaintenanceTab() {
  return (
    <div className="space-y-4">
      <p className="max-w-prose text-sm text-fg-muted">
        Housekeeping for the files Civex stores.
      </p>
      <GCPanel />
    </div>
  )
}
