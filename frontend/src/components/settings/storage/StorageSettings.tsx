import { useSearchParams } from 'react-router'
import { TabNav, TabPanel, type TabDef } from '../../ui'
import { useFeatures } from '../../../hooks/useFeatures'
import type { StorageTab } from '../../../hooks/useStorageAttention'
import { BucketStorage } from './BucketStorage'
import { CollectionsTab } from './CollectionsTab'
import { StorageAttention } from './StorageAttention'
import { Slot } from '../../host/Slot'
import { TasksTab } from './TasksTab'
import { VolumesTab } from './VolumesTab'

type TabId = StorageTab

const TABS: TabDef<TabId>[] = [
  { id: 'volumes', label: 'Volumes' },
  { id: 'collections', label: 'Collections' },
  { id: 'tasks', label: 'Tasks' },
]

/** Settings > Storage: the volumes files live on, which collections use which,
 * and housekeeping. The tab and any volume filter live in the address
 * (`?tab=collections&volume=archive`), so every view can be linked to. */
export default function StorageSettings() {
  const features = useFeatures()
  // A project whose files are in a bucket has no drives: there is only the bucket.
  if (!features.has('volumes'))
    return (
      <div className="space-y-5">
        <Slot name="storage.summary" />
        <BucketStorage />
      </div>
    )
  return <DriveStorage />
}

/** The drives files live on, which collections use which, and housekeeping. */
function DriveStorage() {
  const [params, setParams] = useSearchParams()
  // Addresses from before Moves and Maintenance became Tasks still land there.
  const asked = params.get('tab')
  const wanted =
    asked === 'transfers' || asked === 'maintenance' ? 'tasks' : asked
  const tab = TABS.find((t) => t.id === wanted)?.id ?? 'volumes'
  const volumeFilter = params.get('volume')

  function go(id: TabId) {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (id === 'volumes') next.delete('tab')
        else next.set('tab', id)
        if (id !== 'collections') {
          next.delete('volume')
          next.delete('focus')
        }
        return next
      },
      { replace: true },
    )
  }

  return (
    <div className="space-y-5">
      <Slot name="storage.summary" />
      <StorageAttention onGo={go} />

      <TabNav label="Storage" tabs={TABS} value={tab} onChange={go} />

      <TabPanel id="volumes" value={tab}>
        <VolumesTab />
      </TabPanel>
      <TabPanel id="collections" value={tab}>
        <CollectionsTab
          focusId={params.get('focus')}
          volumeFilter={volumeFilter}
          onClearVolumeFilter={() =>
            setParams(
              (prev) => {
                const next = new URLSearchParams(prev)
                next.delete('volume')
                return next
              },
              { replace: true },
            )
          }
          onGoToVolumes={() => go('volumes')}
        />
      </TabPanel>
      <TabPanel id="tasks" value={tab}>
        <TasksTab
          preset={
            params.get('from') || params.get('collection')
              ? {
                  source: params.get('from') ?? undefined,
                  collectionId: params.get('collection') ?? undefined,
                  target: params.get('to') ?? undefined,
                }
              : undefined
          }
        />
      </TabPanel>
    </div>
  )
}
