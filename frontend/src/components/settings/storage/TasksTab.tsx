import { useState } from 'react'
import { useVolumes } from '../../../hooks/useStore'
import { formatSize } from '../../../utils/storage'
import { Button, Card } from '../../ui'
import { CleanUpDialog } from './CleanUpDialog'
import { NewTransferModal, type TransferPreset } from './NewTransferModal'
import { TransfersTab } from './TransfersTab'

/** Things to do to stored files: move them between volumes, and clear out the
 * ones nothing uses. Each is one button; moves already started are listed
 * below, with their progress. */
export function TasksTab({ preset }: { preset?: TransferPreset }) {
  const [moving, setMoving] = useState<TransferPreset | null>(preset ?? null)
  const [cleaning, setCleaning] = useState(false)
  const { data: volumes = [] } = useVolumes()
  const unused = volumes.reduce((sum, v) => sum + (v.unused_bytes ?? 0), 0)

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2">
        <Card
          title="Move files"
          action={
            <Button size="sm" variant="primary" onClick={() => setMoving({})}>
              Move files…
            </Button>
          }
        >
          <p className="text-sm text-fg-muted">
            Empty a volume before you unplug it, or gather a collection onto one
            drive. Moves run one at a time, in the order you ask for them, and
            every file is checked before the original is removed.
          </p>
        </Card>
        <Card
          title="Clean up unused files"
          action={
            <Button size="sm" onClick={() => setCleaning(true)}>
              Clean up…
            </Button>
          }
        >
          <p className="text-sm text-fg-muted">
            {unused > 0
              ? `About ${formatSize(unused)} is stored that no record or workflow uses. `
              : 'Free the space taken by files that no record or workflow uses. '}
            You see exactly what would go before anything is deleted.
          </p>
        </Card>
      </div>

      <TransfersTab />

      {moving && (
        <NewTransferModal preset={moving} onClose={() => setMoving(null)} />
      )}
      {cleaning && <CleanUpDialog onClose={() => setCleaning(false)} />}
    </div>
  )
}
