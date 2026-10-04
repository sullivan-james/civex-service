import { Suspense } from 'react'
import { Outlet, useLocation, useSearchParams } from 'react-router'
import { InfoTip, Page, Skeleton, TabNav } from '../../components/ui'

/** Settings is a set of pages, one per area, each with its own address
 * (`/settings/storage`), so a section can be linked to and none has to share a
 * long scroll with the others. */
const settingsSections = [
  {
    to: 'appearance',
    label: 'Appearance',
    info: 'System follows your OS setting.',
  },
  {
    to: 'database',
    label: 'Database',
    info: 'Where this project’s records are stored. You can move them to another kind of database at any time; your original is kept.',
  },
  {
    to: 'storage',
    label: 'Storage',
    info: 'Where Civex keeps your files, and which collections use which volume.',
  },
  {
    to: 'recently-deleted',
    label: 'Recently Deleted',
    info: 'Deleted schemas, collections and records can be restored until they are permanently purged.',
  },
  {
    to: 'map',
    label: 'Map',
    info: 'The location editor draws built-in coastlines and a grid, so it works offline. For street-level detail, point it at a tile server; you are responsible for that provider’s terms of use.',
  },
  {
    to: 'advanced',
    label: 'Advanced',
    info: 'Power-user surfaces: the terminal, raw YAML workflow editing and the plugin editors.',
  },
] as const

/** The tabs inside Settings > Storage, by their address (`?tab=`). */
const STORAGE_TABS: Record<string, string> = {
  collections: 'Collections',
  tasks: 'Tasks',
  transfers: 'Tasks',
  maintenance: 'Tasks',
}

export default function SettingsLayout() {
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const current = settingsSections.find((s) => pathname.split('/')[2] === s.to)
  // The tab says which area, and for Storage which of its tabs.
  const storageTab =
    current?.to === 'storage'
      ? (STORAGE_TABS[params.get('tab') ?? ''] ?? 'Volumes')
      : undefined
  return (
    <Page
      title="Settings"
      documentTitle={[storageTab ?? '', current?.label ?? '', 'Settings']}
    >
      <div className="flex flex-col gap-6 md:flex-row md:gap-10">
        <div className="shrink-0 md:w-48">
          <TabNav
            label="Settings sections"
            orientation="vertical"
            tabs={settingsSections.map((section) => ({
              id: section.to,
              label: section.label,
              to: section.to,
            }))}
          />
        </div>
        <div className="min-w-0 flex-1 space-y-5">
          {current && (
            <h2 className="flex items-center gap-1 text-base font-semibold text-fg">
              {current.label}
              <InfoTip side="bottom">{current.info}</InfoTip>
            </h2>
          )}
          {/* Sections load on demand; the section list stays put meanwhile. */}
          <Suspense
            fallback={
              <div className="space-y-3" aria-hidden="true">
                <Skeleton className="h-6 w-40" />
                <Skeleton className="h-32 w-full" />
              </div>
            }
          >
            <Outlet />
          </Suspense>
        </div>
      </div>
    </Page>
  )
}
