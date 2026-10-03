import { useSearchParams } from 'react-router'
import { Tabs, type TabDef } from '../../ui'
import { CollectionsTab } from './CollectionsTab'
import { MaintenanceTab } from './MaintenanceTab'
import { TransfersTab } from './TransfersTab'
import { VolumesTab } from './VolumesTab'

type TabId = 'volumes' | 'collections' | 'transfers' | 'maintenance'

const TABS: TabDef<TabId>[] = [
  { id: 'volumes', label: 'Volumes' },
  { id: 'collections', label: 'Collections' },
  { id: 'transfers', label: 'Moves' },
  { id: 'maintenance', label: 'Maintenance' },
]

/** Settings > Storage: the volumes files live on, which collections use which,
 * and housekeeping. The tab and any volume filter live in the address
 * (`?tab=collections&volume=archive`), so every view can be linked to. */
export default function StorageSettings() {
  const [params, setParams] = useSearchParams()
  const tab = TABS.find((t) => t.id === params.get('tab'))?.id ?? 'volumes'
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
        {tab === 'transfers' && (
          <TransfersTab
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
        {tab === 'maintenance' && <MaintenanceTab />}
      </div>
    </div>
  )
}
