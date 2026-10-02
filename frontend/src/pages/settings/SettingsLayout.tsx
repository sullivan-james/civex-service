import { Suspense } from 'react'
import { NavLink, Outlet } from 'react-router'
import { Page, Skeleton } from '../../components/ui'

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
        <nav aria-label="Settings sections" className="shrink-0 md:w-48">
          <ul className="flex gap-1 overflow-x-auto md:flex-col md:overflow-visible">
            {settingsSections.map((section) => (
              <li key={section.to}>
                <NavLink
                  to={section.to}
                  className={({ isActive }) =>
                    `block whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium ${
                      isActive
                        ? 'bg-accent-subtle text-accent'
                        : 'text-fg-muted hover:bg-canvas-subtle hover:text-fg'
                    }`
                  }
                >
                  {section.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
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
