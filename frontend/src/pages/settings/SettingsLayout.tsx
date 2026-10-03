import { Suspense } from 'react'
import { Outlet } from 'react-router'
import { Page, Skeleton, TabNav } from '../../components/ui'

/** Settings is a set of pages, one per area, each with its own address
 * (`/settings/storage`), so a section can be linked to and none has to share a
 * long scroll with the others. */
const settingsSections = [
  { to: 'appearance', label: 'Appearance' },
  { to: 'database', label: 'Database' },
  { to: 'storage', label: 'Storage' },
  { to: 'recently-deleted', label: 'Recently Deleted' },
  { to: 'map', label: 'Map' },
  { to: 'advanced', label: 'Advanced' },
] as const

export default function SettingsLayout() {
  return (
    <Page title="Settings">
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
        <div className="min-w-0 flex-1">
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
