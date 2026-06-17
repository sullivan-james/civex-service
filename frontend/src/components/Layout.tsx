import { type ReactNode, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { remoteApi, type SyncResult } from '../api/remote'

declare global {
  interface Window {
    pywebview?: { api: {
      open_project: () => Promise<{ ok?: boolean; error?: string } | null>
      create_project: () => Promise<{ ok?: boolean; error?: string } | null>
    } }
  }
}

const isDesktop = typeof window !== 'undefined' && !!window.pywebview

const tabs = [
  { to: '/datasets',  label: 'Datasets' },
  { to: '/schemas',   label: 'Schemas' },
  { to: '/workflows', label: 'Workflows' },
  { to: '/jobs',      label: 'Jobs' },
  { to: '/terminal',  label: 'Terminal' },
]

function SyncMessage({ result, error, op }: { result: SyncResult | null; error: string | null; op: 'push' | 'pull' }) {
  if (error) return <span className="text-[#f85149] text-xs">{error}</span>
  if (!result) return null
  return (
    <span className="text-[#3fb950] text-xs">
      {op === 'push' ? 'Pushed' : 'Pulled'} — {result.records}r {result.schemas}s {result.datasets}d
    </span>
  )
}

export default function Layout({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [syncing, setSyncing] = useState<'push' | 'pull' | null>(null)
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)
  const [lastOp, setLastOp] = useState<'push' | 'pull'>('push')

  const { data: remote } = useQuery({
    queryKey: ['remote-status'],
    queryFn: remoteApi.status,
    retry: false,
    staleTime: 30_000,
  })

  async function runSync(op: 'push' | 'pull') {
    setSyncing(op)
    setSyncResult(null)
    setSyncError(null)
    setLastOp(op)
    try {
      const result = op === 'push' ? await remoteApi.push() : await remoteApi.pull()
      setSyncResult(result)
      // Invalidate all data queries so the UI reflects pulled changes.
      if (op === 'pull') {
        queryClient.invalidateQueries()
      }
    } catch (e: unknown) {
      setSyncError(e instanceof Error ? e.message : String(e))
    } finally {
      setSyncing(null)
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Top navbar */}
      <header className="bg-[#24292f] px-6 py-3 flex items-center gap-4">
        <span className="text-[#f0f6fc] font-semibold text-base tracking-tight">civex</span>

        <button
          onClick={() => queryClient.invalidateQueries()}
          title="Refresh all data"
          className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded border border-[#444c56] bg-[#2d333b] text-[#adbac7] hover:bg-[#373e47] hover:text-[#e6edf3] transition-colors"
        >
          <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
            <path d="M1.705 8.005a.75.75 0 0 1 .834.656 5.5 5.5 0 0 0 9.592 2.97l-1.204-1.204a.25.25 0 0 1 .177-.427h3.646a.25.25 0 0 1 .25.25v3.646a.25.25 0 0 1-.427.177l-1.38-1.38A7.002 7.002 0 0 1 1.05 8.84a.75.75 0 0 1 .656-.834ZM8 2.5a5.487 5.487 0 0 0-4.131 1.869l1.204 1.204A.25.25 0 0 1 4.896 6H1.25A.25.25 0 0 1 1 5.75V2.104a.25.25 0 0 1 .427-.177l1.38 1.38A7.002 7.002 0 0 1 14.95 7.16a.75.75 0 0 1-1.49.178A5.5 5.5 0 0 0 8 2.5Z"/>
          </svg>
          Refresh
        </button>

        {isDesktop && (
          <div className="flex items-center gap-1 ml-2">
            <button
              onClick={() => window.pywebview!.api.open_project()}
              title="Open a different civex project"
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded border border-[#444c56] bg-[#2d333b] text-[#adbac7] hover:bg-[#373e47] hover:text-[#e6edf3] transition-colors"
            >
              <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
                <path d="M1.75 1A1.75 1.75 0 0 0 0 2.75v10.5C0 14.216.784 15 1.75 15h12.5A1.75 1.75 0 0 0 16 13.25v-8.5A1.75 1.75 0 0 0 14.25 3H7.5a.25.25 0 0 1-.2-.1l-.9-1.2C6.07 1.26 5.55 1 5 1H1.75z"/>
              </svg>
              Open project
            </button>
            <button
              onClick={() => window.pywebview!.api.create_project()}
              title="Create a new civex project"
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded border border-[#444c56] bg-[#2d333b] text-[#adbac7] hover:bg-[#373e47] hover:text-[#e6edf3] transition-colors"
            >
              <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
                <path d="M7.75 2a.75.75 0 0 1 .75.75V7h4.25a.75.75 0 0 1 0 1.5H8.5v4.25a.75.75 0 0 1-1.5 0V8.5H2.75a.75.75 0 0 1 0-1.5H7V2.75A.75.75 0 0 1 7.75 2z"/>
              </svg>
              New project
            </button>
          </div>
        )}

        <div className="flex-1" />

        {remote && (
          <div className="flex items-center gap-2">
            <SyncMessage result={syncResult} error={syncError} op={lastOp} />

            <button
              onClick={() => runSync('pull')}
              disabled={syncing !== null}
              title={`Pull from ${remote.url}`}
              className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded border border-[#444c56] bg-[#2d333b] text-[#adbac7] hover:bg-[#373e47] hover:text-[#e6edf3] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {syncing === 'pull' ? (
                <Spinner />
              ) : (
                <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
                  <path d="M8 2a.75.75 0 0 1 .75.75v6.69l2.72-2.72a.75.75 0 1 1 1.06 1.06l-4 4a.75.75 0 0 1-1.06 0l-4-4a.75.75 0 0 1 1.06-1.06L7.25 9.44V2.75A.75.75 0 0 1 8 2z"/>
                  <path d="M2 13.25a.75.75 0 0 1 .75-.75h10.5a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1-.75-.75z"/>
                </svg>
              )}
              Pull
            </button>

            <button
              onClick={() => runSync('push')}
              disabled={syncing !== null}
              title={`Push to ${remote.url}`}
              className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded border border-[#444c56] bg-[#2d333b] text-[#adbac7] hover:bg-[#373e47] hover:text-[#e6edf3] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {syncing === 'push' ? (
                <Spinner />
              ) : (
                <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
                  <path d="M8 14a.75.75 0 0 1-.75-.75V6.56L4.53 9.28a.75.75 0 0 1-1.06-1.06l4-4a.75.75 0 0 1 1.06 0l4 4a.75.75 0 0 1-1.06 1.06L8.75 6.56v6.69A.75.75 0 0 1 8 14z"/>
                  <path d="M2 2.75a.75.75 0 0 1 .75-.75h10.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 2.75z"/>
                </svg>
              )}
              Push
            </button>
          </div>
        )}
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

function Spinner() {
  return (
    <svg className="animate-spin" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden>
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" strokeLinecap="round"/>
    </svg>
  )
}
