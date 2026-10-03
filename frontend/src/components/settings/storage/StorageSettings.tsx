import { useSearchParams } from 'react-router'
import { Tabs, type TabDef } from '../../ui'
import type { StorageTab } from '../../../hooks/useStorageAttention'
import { CollectionsTab } from './CollectionsTab'
import { StorageAttention } from './StorageAttention'
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
        if (id !== 'collections') next.delete('volume')
        return next
      },
      { replace: true },
    )
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-fg">Storage</h2>
        <p className="mt-1 text-sm text-fg-muted">
          Where Civex keeps your files, and which collections use which volume.
        </p>
      </div>

      <StorageAttention onGo={go} />

      <Tabs label="Storage" tabs={TABS} value={tab} onChange={go} />

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === 'volumes' && <VolumesTab />}
        {tab === 'collections' && (
          <CollectionsTab
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
        )}
        {tab === 'tasks' && (
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
        )}
      </div>
    </div>
  )
}
