import {
  type ComponentType,
  type ReactNode,
  useId,
  useRef,
  useState,
} from 'react'
import { NavLink } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Group,
  Panel,
  Separator,
  useDefaultLayout,
} from 'react-resizable-panels'
import { remoteApi } from '../api/remote'
import { errorMessage } from '../lib/errors'
import { useUISettings } from '../hooks/useUISettings'
import { useDialogA11y } from '../hooks/useDialogA11y'
import AiAttestationGate from './ai/AiAttestationGate'
import AiPanel from './ai/AiPanel'
import { useToast } from './ui/ToastProvider'
import { IconButton } from './ui/IconButton'
import { Spinner } from './ui/Spinner'
import { Menu as Dropdown } from './ui/Menu'
import {
  RefreshCw,
  Sparkles,
  Settings,
  ExternalLink,
  ArrowDownToLine,
  ArrowUpToLine,
  ArrowRightLeft,
  FolderOpen,
  FolderPlus,
  Folder,
  ChevronDown,
  LayoutGrid,
  Table,
  Database,
  Workflow,
  ListChecks,
  BarChart3,
  SquareTerminal,
  Puzzle,
  PanelLeftClose,
  PanelLeftOpen,
  Menu,
  X,
  Trash2,
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

const NAV_COLLAPSED_KEY = 'civex-nav-collapsed'

const navButtonClass =
  'inline-flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-md border border-nav-border bg-nav-surface text-nav-fg-muted hover:bg-nav-surface-hover hover:text-nav-fg transition-colors'

// The breakpoint at which the persistent rail gives way to a drawer (not one
// of Tailwind's default steps) is written out as the literal `min-[900px]:`
// variant at each call site below — Tailwind's static scanner extracts class
// candidates from the source text itself, so building the variant from a JS
// constant at runtime would leave the styles ungenerated.

function readCollapsed(): boolean {
  return (
    typeof window !== 'undefined' &&
    localStorage.getItem(NAV_COLLAPSED_KEY) === '1'
  )
}

interface NavItemDef {
  to: string
  label: string
  icon: ComponentType<{
    size?: number
    className?: string
    'aria-hidden'?: boolean | 'true'
  }>
}

interface NavGroupDef {
  heading: string
  items: NavItemDef[]
  // De-emphasized groups are setup-time or power-user surfaces a
  // first-time researcher doesn't need on day one (Structure, Advanced) —
  // as opposed to the everyday surfaces (Data, Automation).
  secondary?: boolean
}

const navGroups: NavGroupDef[] = [
  {
    heading: 'Data',
    items: [
      { to: '/collections', label: 'Collections', icon: LayoutGrid },
      { to: '/views', label: 'Views', icon: Table },
      { to: '/trash', label: 'Recently Deleted', icon: Trash2 },
    ],
  },
  {
    heading: 'Insights',
    items: [{ to: '/analytics', label: 'Analytics', icon: BarChart3 }],
  },
  {
    heading: 'Structure',
    items: [{ to: '/schemas', label: 'Schemas', icon: Database }],
    secondary: true,
  },
  {
    heading: 'Automation',
    items: [
      { to: '/workflows', label: 'Workflows', icon: Workflow },
      { to: '/runs', label: 'Runs', icon: ListChecks },
    ],
  },
  {
    heading: 'Advanced',
    items: [
      { to: '/plugins', label: 'Plugins', icon: Puzzle },
      { to: '/terminal', label: 'Terminal', icon: SquareTerminal },
    ],
    secondary: true,
  },
]

const settingsNavItem: NavItemDef = {
  to: '/settings',
  label: 'Settings',
  icon: Settings,
}

function NavItem({
  to,
  label,
  icon: Icon,
  collapsed,
  secondary,
  onNavigate,
}: NavItemDef & {
  collapsed: boolean
  secondary?: boolean
  onNavigate?: () => void
}) {
  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      title={collapsed ? label : undefined}
      aria-label={collapsed ? label : undefined}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
          collapsed ? 'justify-center px-0' : ''
        } ${
          isActive
            ? 'bg-accent-subtle text-accent'
            : secondary
              ? 'text-fg-subtle hover:bg-canvas-inset hover:text-fg'
              : 'text-fg-muted hover:bg-canvas-inset hover:text-fg'
        }`
      }
    >
      <Icon size={18} className="shrink-0" aria-hidden="true" />
      {!collapsed && <span className="truncate">{label}</span>}
    </NavLink>
  )
}

function NavGroupHeading({
  children,
  secondary,
}: {
  children: ReactNode
  secondary?: boolean
}) {
  return (
    <div
      className={`px-3 pb-1 pt-4 mt-2 text-xs font-semibold uppercase tracking-wider first:pt-0 text-fg-subtle ${
        secondary ? 'opacity-70' : ''
      }`}
    >
      {children}
    </div>
  )
}

function NavGroups({
  collapsed,
  showAdvanced,
  onNavigate,
}: {
  collapsed: boolean
  showAdvanced: boolean
  onNavigate?: () => void
}) {
  const groups = navGroups.filter(
    (group) => showAdvanced || group.heading !== 'Advanced',
  )
  return (
    <div className="flex flex-col">
      {groups.map((group) => (
        <div key={group.heading}>
          {!collapsed && (
            <NavGroupHeading secondary={group.secondary}>
              {group.heading}
            </NavGroupHeading>
          )}
          <div className="flex flex-col gap-1">
            {group.items.map((item) => (
              <NavItem
                key={item.to}
                {...item}
                collapsed={collapsed}
                secondary={group.secondary}
                onNavigate={onNavigate}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export default function Layout({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [syncing, setSyncing] = useState<'push' | 'pull' | null>(null)
  const [syncAnnouncement, setSyncAnnouncement] = useState('')
  const [aiOpen, setAiOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const drawerWrapperRef = useRef<HTMLDivElement>(null)
  const drawerRef = useRef<HTMLDivElement>(null)
  const drawerTitleId = useId()
  const toast = useToast()

  const { data: remote } = useQuery({
    queryKey: ['remote-status'],
    queryFn: remoteApi.status,
    retry: false,
    staleTime: 30_000,
  })

  const { data: uiSettings } = useUISettings()
  const showAdvanced = uiSettings?.show_advanced ?? false

  const aiSplitLayout = useDefaultLayout({
    id: 'civex-ai-split',
    storage: localStorage,
    panelIds: ['main', 'ai'],
  })

  useDialogA11y({
    open: drawerOpen,
    onClose: closeDrawer,
    rootRef: drawerWrapperRef,
    dialogRef: drawerRef,
  })

  function closeDrawer() {
    setDrawerOpen(false)
  }

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev
      localStorage.setItem(NAV_COLLAPSED_KEY, next ? '1' : '0')
      return next
    })
  }

  async function runSync(op: 'push' | 'pull') {
    setSyncing(op)
    const verb = op === 'push' ? 'Push' : 'Pull'
    setSyncAnnouncement(
      op === 'push' ? 'Pushing to remote…' : 'Pulling from remote…',
    )
    try {
      const result =
        op === 'push' ? await remoteApi.push() : await remoteApi.pull()
      toast.success(
        `${verb}ed — ${result.records}r ${result.schemas}s ${result.datasets}d`,
      )
      setSyncAnnouncement(
        `${verb} complete. ${result.records} record${result.records === 1 ? '' : 's'}, ` +
          `${result.schemas} record type${result.schemas === 1 ? '' : 's'} updated.`,
      )
      // Invalidate all data queries so the UI reflects pulled changes.
      if (op === 'pull') {
        queryClient.invalidateQueries()
      }
    } catch (e: unknown) {
      toast.error(errorMessage(e))
      setSyncAnnouncement(`${verb} failed.`)
    } finally {
      setSyncing(null)
    }
  }

  return (
    <div className="h-screen flex flex-col">
      {/* Top bar — always dark regardless of theme, so it needs its own
          border to stay visible against a dark-theme canvas instead of
          blending into it. Global actions only; section navigation lives
          in the left rail below. */}
      <header className="shrink-0 bg-nav-bg border-b border-nav-border px-4 py-2.5 flex items-center gap-3">
        <button
          onClick={() => setDrawerOpen(true)}
          aria-label="Open navigation"
          className="min-[900px]:hidden inline-flex items-center justify-center h-8 w-8 rounded-md border border-nav-border bg-nav-surface text-nav-fg-muted hover:bg-nav-surface-hover hover:text-nav-fg transition-colors"
        >
          <Menu size={16} aria-hidden="true" />
        </button>

        <NavLink
          to="/"
          className="text-nav-fg font-semibold text-base tracking-tight"
        >
          civex
        </NavLink>

        <button
          onClick={() => queryClient.refetchQueries({ type: 'active' })}
          title="Refresh all data"
          className={navButtonClass}
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

        {isDesktop && (
          <>
            <div className="h-5 w-px bg-nav-border" aria-hidden="true" />
            <Dropdown
              align="left"
              items={[
                {
                  label: 'Open project',
                  icon: FolderOpen,
                  onClick: () => window.pywebview!.api.open_project(),
                },
                {
                  label: 'New project',
                  icon: FolderPlus,
                  onClick: () => window.pywebview!.api.create_project(),
                },
                {
                  label: fileManagerLabel(),
                  icon: Folder,
                  onClick: async () => {
                    const r = await window.pywebview!.api.open_data_dir()
                    if (r?.error) toast.error(r.error)
                  },
                },
              ]}
              trigger={({ toggle }) => (
                <button
                  onClick={toggle}
                  title="Project"
                  className={navButtonClass}
                >
                  <Folder size={12} />
                  Project
                  <ChevronDown size={12} />
                </button>
              )}
            />
          </>
        )}

        <div className="flex-1" />

        {remote && (
          <div aria-busy={syncing !== null}>
            <span role="status" aria-live="polite" className="sr-only">
              {syncAnnouncement}
            </span>
            <Dropdown
              items={[
                {
                  label: 'Pull',
                  icon: ArrowDownToLine,
                  disabled: syncing !== null,
                  onClick: () => runSync('pull'),
                },
                {
                  label: 'Push',
                  icon: ArrowUpToLine,
                  disabled: syncing !== null,
                  onClick: () => runSync('push'),
                },
              ]}
              trigger={({ toggle }) => (
                <button
                  onClick={toggle}
                  disabled={syncing !== null}
                  title={`Sync with ${remote.url}`}
                  className={`${navButtonClass} disabled:opacity-50 disabled:cursor-not-allowed`}
                >
                  {syncing !== null ? (
                    <Spinner size={12} />
                  ) : (
                    <ArrowRightLeft size={12} />
                  )}
                  Sync
                  <ChevronDown size={12} />
                </button>
              )}
            />
          </div>
        )}
      </header>

      <div className="flex-1 flex min-h-0">
        {/* Persistent left nav, collapsible to an icon rail. Hidden below
            the drawer breakpoint in favour of the off-canvas nav rendered
            further down. */}
        <nav
          aria-label="Primary"
          className={`hidden min-[900px]:flex shrink-0 flex-col border-r border-border bg-canvas-subtle py-3 ${
            collapsed ? 'w-16 px-2' : 'w-56 px-3'
          }`}
        >
          <div
            className={`flex pb-5 ${collapsed ? 'justify-center' : 'justify-end'}`}
          >
            <IconButton
              icon={collapsed ? PanelLeftOpen : PanelLeftClose}
              aria-label={
                collapsed ? 'Expand navigation' : 'Collapse navigation'
              }
              onClick={toggleCollapsed}
            />
          </div>
          <NavGroups collapsed={collapsed} showAdvanced={showAdvanced} />
          <div className="flex-1" />
          <div className="flex flex-col gap-1 pt-2 border-t border-border-muted">
            {!collapsed && <NavGroupHeading>Settings</NavGroupHeading>}
            <NavItem {...settingsNavItem} collapsed={collapsed} />
          </div>
        </nav>

        {/* Off-canvas nav drawer for narrow viewports. */}
        {drawerOpen && (
          <div
            ref={drawerWrapperRef}
            className="fixed inset-0 z-40 min-[900px]:hidden"
          >
            <div
              className="absolute inset-0 bg-overlay-scrim"
              onClick={closeDrawer}
            />
            <div
              ref={drawerRef}
              role="dialog"
              aria-modal="true"
              aria-labelledby={drawerTitleId}
              tabIndex={-1}
              className="absolute inset-y-0 left-0 w-64 max-w-[80vw] bg-canvas border-r border-border shadow-lg flex flex-col py-3 px-3 focus:outline-none"
            >
              <div className="flex items-center justify-between pb-2">
                <span
                  id={drawerTitleId}
                  className="text-sm font-semibold text-fg px-1"
                >
                  Navigation
                </span>
                <IconButton
                  icon={X}
                  aria-label="Close navigation"
                  onClick={closeDrawer}
                />
              </div>
              <NavGroups
                collapsed={false}
                showAdvanced={showAdvanced}
                onNavigate={closeDrawer}
              />
              <div className="flex-1" />
              <div className="flex flex-col gap-1 pt-2 border-t border-border-muted">
                <NavGroupHeading>Settings</NavGroupHeading>
                <NavItem
                  {...settingsNavItem}
                  collapsed={false}
                  onNavigate={closeDrawer}
                />
              </div>
            </div>
          </div>
        )}

        {/* Page content — its own scroll container, independent of the nav
            rail and top bar. Split with the AI panel (instead of it
            overlaying the page) when open, so both stay usable at once;
            the split ratio is remembered across reloads. */}
        {aiOpen ? (
          <Group
            orientation="horizontal"
            className="flex-1 min-w-0"
            defaultLayout={aiSplitLayout.defaultLayout}
            onLayoutChanged={aiSplitLayout.onLayoutChanged}
          >
            <Panel id="main" minSize="30%" className="h-full flex flex-col">
              <main className="flex-1 min-h-0 overflow-y-auto">
                <div className="max-w-[1600px] mx-auto px-6 py-6">
                  {children}
                </div>
              </main>
            </Panel>
            <Separator
              aria-label="Resize AI panel"
              className="w-1 bg-border hover:bg-accent active:bg-accent transition-colors cursor-col-resize"
            />
            <Panel id="ai" defaultSize="32%" minSize="22%" maxSize="60%">
              <AiAttestationGate open={aiOpen} onClose={() => setAiOpen(false)}>
                <AiPanel onClose={() => setAiOpen(false)} />
              </AiAttestationGate>
            </Panel>
          </Group>
        ) : (
          <main className="flex-1 min-w-0 overflow-y-auto">
            <div className="max-w-[1600px] mx-auto px-6 py-6">{children}</div>
          </main>
        )}
      </div>

      {/* Footer */}
      <footer className="shrink-0 border-t border-border bg-canvas px-6 py-3 flex items-center justify-center gap-4">
        <NavLink
          to="/legal"
          className="text-xs text-fg-muted hover:text-fg hover:underline"
        >
          Licenses &amp; policies
        </NavLink>
        <a
          href="/docs"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-fg-muted hover:text-fg hover:underline"
        >
          API docs <ExternalLink size={12} />
        </a>
      </footer>
    </div>
  )
}
