import { type ReactNode, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { remoteApi } from '../api/remote'
import { errorMessage } from '../lib/errors'
import AiAttestationGate from './ai/AiAttestationGate'
import { useToast } from './ui/ToastProvider'
import {
  RefreshCw,
  Sparkles,
  Settings,
  ExternalLink,
  ArrowDownToLine,
  ArrowUpToLine,
  FolderOpen,
  FolderPlus,
  Folder,
} from './ui/icons'

declare global {
  interface Window {
    pywebview?: {
      api: {
        open_project: () => Promise<{ ok?: boolean; error?: string } | null>
        create_project: () => Promise<{ ok?: boolean; error?: string } | null>
        browse_folder: () => Promise<{ path: string | null }>
        open_data_dir: () => Promise<{ ok?: boolean; error?: string }>
      }
    }
  }
}

const isDesktop = typeof window !== 'undefined' && !!window.pywebview

// pywebview runs inside a native shell, so navigator.platform reflects the
// host OS reliably enough to pick the right verb for each platform's file manager.
function fileManagerLabel(): string {
  const platform = typeof navigator !== 'undefined' ? navigator.platform : ''
  if (/Mac/i.test(platform)) return 'Reveal in Finder'
  if (/Win/i.test(platform)) return 'Show in Explorer'
  return 'Open data folder'
}

const tabs = [
  { to: '/collections', label: 'Collections' },
  { to: '/schemas', label: 'Schemas' },
  { to: '/workflows', label: 'Workflows' },
  { to: '/runs', label: 'Runs' },
  { to: '/terminal', label: 'Terminal' },
]

export default function Layout({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const settingsActive = location.pathname.startsWith('/settings')
  const [syncing, setSyncing] = useState<'push' | 'pull' | null>(null)
  const [aiOpen, setAiOpen] = useState(false)
  const toast = useToast()

  const { data: remote } = useQuery({
    queryKey: ['remote-status'],
    queryFn: remoteApi.status,
    retry: false,
    staleTime: 30_000,
  })

  async function runSync(op: 'push' | 'pull') {
    setSyncing(op)
    try {
      const result =
        op === 'push' ? await remoteApi.push() : await remoteApi.pull()
      const verb = op === 'push' ? 'Pushed' : 'Pulled'
      toast.success(
        `${verb} — ${result.records}r ${result.schemas}s ${result.datasets}d`,
      )
      // Invalidate all data queries so the UI reflects pulled changes.
      if (op === 'pull') {
        queryClient.invalidateQueries()
      }
    } catch (e: unknown) {
      toast.error(errorMessage(e))
    } finally {
      setSyncing(null)
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Top navbar — always dark regardless of theme, so it needs its own
          border to stay visible against a dark-theme canvas instead of
          blending into it. */}
      <header className="bg-nav-bg border-b border-nav-border px-6 py-3 flex items-center gap-4">
        <span className="text-nav-fg font-semibold text-base tracking-tight">
          civex
        </span>

        <button
          onClick={() => queryClient.refetchQueries({ type: 'active' })}
          title="Refresh all data"
          className="inline-flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-md border border-nav-border bg-nav-surface text-nav-fg-muted hover:bg-nav-surface-hover hover:text-nav-fg transition-colors"
        >
          <RefreshCw size={12} />
          Refresh
        </button>

        <button
          onClick={() => setAiOpen((o) => !o)}
          title="Open AI assistant"
          className={`inline-flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-md border transition-colors ${
            aiOpen
              ? 'border-accent bg-accent text-fg-on-emphasis'
              : 'border-nav-border bg-nav-surface text-nav-fg-muted hover:bg-nav-surface-hover hover:text-nav-fg'
          }`}
        >
          <Sparkles size={12} /> Ask AI
        </button>

        <button
          onClick={() => navigate('/settings')}
          title="Settings"
          className={`inline-flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-md border transition-colors ${
            settingsActive
              ? 'border-accent bg-accent text-fg-on-emphasis'
              : 'border-nav-border bg-nav-surface text-nav-fg-muted hover:bg-nav-surface-hover hover:text-nav-fg'
          }`}
        >
          <Settings size={12} />
          Settings
        </button>

        {isDesktop && (
          <div className="flex items-center gap-1 ml-2">
            <button
              onClick={() => window.pywebview!.api.open_project()}
              title="Open a different civex project"
              className="inline-flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-md border border-nav-border bg-nav-surface text-nav-fg-muted hover:bg-nav-surface-hover hover:text-nav-fg transition-colors"
            >
              <FolderOpen size={12} />
              Open project
            </button>
            <button
              onClick={() => window.pywebview!.api.create_project()}
              title="Create a new civex project"
              className="inline-flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-md border border-nav-border bg-nav-surface text-nav-fg-muted hover:bg-nav-surface-hover hover:text-nav-fg transition-colors"
            >
              <FolderPlus size={12} />
              New project
            </button>
            <button
              onClick={async () => {
                const r = await window.pywebview!.api.open_data_dir()
                if (r?.error) toast.error(r.error)
              }}
              title={`${fileManagerLabel()} — open this project's database directory`}
              className="inline-flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-md border border-nav-border bg-nav-surface text-nav-fg-muted hover:bg-nav-surface-hover hover:text-nav-fg transition-colors"
            >
              <Folder size={12} />
              {fileManagerLabel()}
            </button>
          </div>
        )}

        <div className="flex-1" />

        {remote && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => runSync('pull')}
              disabled={syncing !== null}
              title={`Pull from ${remote.url}`}
              className="inline-flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-md border border-nav-border bg-nav-surface text-nav-fg-muted hover:bg-nav-surface-hover hover:text-nav-fg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {syncing === 'pull' ? <Spinner /> : <ArrowDownToLine size={12} />}
              Pull
            </button>

            <button
              onClick={() => runSync('push')}
              disabled={syncing !== null}
              title={`Push to ${remote.url}`}
              className="inline-flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-md border border-nav-border bg-nav-surface text-nav-fg-muted hover:bg-nav-surface-hover hover:text-nav-fg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {syncing === 'push' ? <Spinner /> : <ArrowUpToLine size={12} />}
              Push
            </button>
          </div>
        )}
      </header>

      {/* Tab bar */}
      <div className="border-b border-border bg-canvas px-6">
        <nav className="flex gap-1 -mb-px">
          {tabs.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                  isActive
                    ? 'border-danger-subtle-border text-fg'
                    : 'border-transparent text-fg-muted hover:text-fg hover:border-border'
                }`
              }
            >
              {label}
            </NavLink>
          ))}
          <a
            href="/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 px-4 py-3 text-sm font-medium border-b-2 border-transparent text-fg-muted hover:text-fg hover:border-border transition-colors"
          >
            API docs <ExternalLink size={12} />
          </a>
        </nav>
      </div>

      {/* Page content */}
      <main className="flex-1 px-6 py-6 max-w-5xl w-full mx-auto">
        {children}
      </main>

      {/* Footer */}
      <footer className="border-t border-border bg-canvas px-6 py-3 text-center">
        <NavLink
          to="/legal"
          className="text-xs text-fg-muted hover:text-fg hover:underline"
        >
          Licenses &amp; policies
        </NavLink>
      </footer>

      <AiAttestationGate open={aiOpen} onClose={() => setAiOpen(false)} />
    </div>
  )
}

function Spinner() {
  return (
    <svg
      className="animate-spin"
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      aria-hidden
    >
      <path
        d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"
        strokeLinecap="round"
      />
    </svg>
  )
}
