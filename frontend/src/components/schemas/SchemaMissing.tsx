import { useState } from 'react'
import { useRestorePlan } from '../../hooks/useRestore'
import { RestoreDialog } from '../trash/RestoreDialog'
import { Button, ErrorState } from '../ui'

/** What a schema's page says when there is no such schema to show. One that was
 * deleted says when and can be restored from here, with the records that went
 * with it; anything else is the plain error. */
export function SchemaMissing({
  id,
  message,
}: {
  id: string
  message: string
}) {
  const { data: plan } = useRestorePlan({ kind: 'schema', ref: id })
  const [restoring, setRestoring] = useState(false)
  if (!plan) return <ErrorState message={message} />
  const when = plan.deleted_at
    ? ` on ${new Date(plan.deleted_at).toLocaleDateString()}`
    : ''
  return (
    <div className="space-y-3">
      <ErrorState
        message={`The schema “${plan.name}” was deleted${when}. It can be restored.`}
      />
      <p className="text-sm text-fg-muted">
        {plan.records > 0
          ? `Restoring it brings back the ${plan.records.toLocaleString()} record${plan.records === 1 ? '' : 's'} deleted with it.`
          : 'No records were deleted with it.'}
      </p>
      <Button variant="primary" onClick={() => setRestoring(true)}>
        Restore…
      </Button>
      {restoring && (
        <RestoreDialog
          target={{ kind: 'schema', ref: id }}
          onClose={() => setRestoring(false)}
        />
      )}
    </div>
  )
}
