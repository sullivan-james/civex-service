import { useState } from 'react'
import { useBucket } from '../../../hooks/useBucket'
import { useFeatures } from '../../../hooks/useFeatures'
import { useVolumes } from '../../../hooks/useStore'
import { formatSize } from '../../../utils/storage'
import { Button, Card } from '../../ui'
import { BucketModal } from './BucketModal'
import { CleanUpDialog } from './CleanUpDialog'
import { NewTransferModal, type TransferPreset } from './NewTransferModal'
import { TransfersTab } from './TransfersTab'

/** Things to do to stored files: move them between volumes, and clear out the
 * ones nothing uses. Each is one button; moves already started are listed
 * below, with their progress. */
export function TasksTab({ preset }: { preset?: TransferPreset }) {
  const [moving, setMoving] = useState<TransferPreset | null>(preset ?? null)
  const [cleaning, setCleaning] = useState(false)
  const [bucketing, setBucketing] = useState(false)
  const choosesStore = useFeatures().has('store_admin')
  const { data: bucket } = useBucket()
  const { data: volumes = [] } = useVolumes()
  const unused = volumes.reduce((sum, v) => sum + (v.unused_bytes ?? 0), 0)

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
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
        {choosesStore && (
          <Card
            title="Keep files in a bucket"
            info="Store this project's files in an S3 bucket (AWS, MinIO, R2) instead of on drives. Files aren't moved, so this is for a project with no files yet."
            action={
              <Button
                size="sm"
                disabled={bucket ? !bucket.can_switch : true}
                title={bucket?.blocked ?? undefined}
                onClick={() => setBucketing(true)}
              >
                Use a bucket…
              </Button>
            }
          />
        )}
      </div>

      <TransfersTab />

      {moving && (
        <NewTransferModal preset={moving} onClose={() => setMoving(null)} />
      )}
      {cleaning && <CleanUpDialog onClose={() => setCleaning(false)} />}
      {bucketing && <BucketModal onClose={() => setBucketing(false)} />}
    </div>
  )
}
