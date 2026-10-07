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
          info="Empty a drive before you unplug it, or gather a collection onto one. Moves run one at a time, and every file is checked before its original is removed."
          action={
            <Button size="sm" variant="primary" onClick={() => setMoving({})}>
              Move files…
            </Button>
          }
        />
        <Card
          title="Clean up unused files"
          info="Files no record or workflow uses. You see what would go before anything is deleted."
          count={unused > 0 ? `about ${formatSize(unused)}` : undefined}
          action={
            <Button size="sm" onClick={() => setCleaning(true)}>
              Clean up…
            </Button>
          }
        />
      </div>

      <TransfersTab />

      {moving && (
        <NewTransferModal preset={moving} onClose={() => setMoving(null)} />
      )}
      {cleaning && <CleanUpDialog onClose={() => setCleaning(false)} />}
    </div>
  )
}
