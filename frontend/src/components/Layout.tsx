import { type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'

const tabs = [
  { to: '/datasets',  label: 'Datasets' },
  { to: '/schemas',   label: 'Schemas' },
  { to: '/workflows', label: 'Workflows' },
  { to: '/jobs',      label: 'Jobs' },
]

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      {/* Top navbar */}
      <header className="bg-[#24292f] px-6 py-3 flex items-center gap-4">
        <span className="text-[#f0f6fc] font-semibold text-base tracking-tight">civex</span>
      </header>

      {/* Tab bar */}
      <div className="border-b border-[#d0d7de] bg-white px-6">
        <nav className="flex gap-1 -mb-px">
          {tabs.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                  isActive
                    ? 'border-[#fd8c73] text-[#1f2328]'
                    : 'border-transparent text-[#656d76] hover:text-[#1f2328] hover:border-[#d0d7de]'
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </div>

      {/* Page content */}
      <main className="flex-1 px-6 py-6 max-w-5xl w-full mx-auto">
        {children}
      </main>
    </div>
  )
}
