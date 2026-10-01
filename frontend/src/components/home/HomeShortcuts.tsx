import { Link } from 'react-router'
import { useJobsPaged } from '../../hooks/useWorkflows'
import { usePins, useRecents } from '../../hooks/usePins'
import { PinCount } from '../PinnedNav'
import { PIN_ICONS } from '../pinIcons'
import { IconButton } from '../ui'
import { AlertTriangle, Star } from '../ui/icons'
import type { NavTarget } from '../../utils/pins'

function AttentionCard({ pin }: { pin: NavTarget }) {
  return (
    <Link
      to={pin.to}
      className="group flex items-center justify-between gap-3 rounded-lg border border-border bg-canvas p-4 transition-colors hover:border-accent-subtle-border hover:bg-canvas-subtle"
    >
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-fg">{pin.label}</p>
        {pin.context && (
          <p className="truncate text-xs text-fg-muted">{pin.context}</p>
        )}
      </div>
      {/* PinCount renders nothing until the figure is known */}
      <span className="text-lg font-semibold tabular-nums text-fg">
        <PinCount target={pin} />
      </span>
    </Link>
  )
}

function FailedRunsCard() {
  const { total } = useJobsPaged(0, 1, 'failed')
  if (total === 0) return null
  return (
    <Link
      to="/runs?status=failed"
      className="flex items-center gap-3 rounded-lg border border-danger-muted bg-danger-subtle p-4 transition-colors hover:border-danger"
    >
      <AlertTriangle size={18} className="shrink-0 text-danger" aria-hidden />
      <div>
        <p className="text-sm font-semibold text-danger">
          {total.toLocaleString()} failed {total === 1 ? 'run' : 'runs'}
        </p>
        <p className="text-xs text-fg-muted">
          Open them to see what went wrong.
        </p>
      </div>
    </Link>
  )
}

/** The top of Home once there is something to come back to: pinned filters
 * with their live counts (and any failed runs) under "Needs your attention",
 * then what was opened lately. Pinned collections and records live in the
 * nav; Home is for what needs working through. */
export function HomeShortcuts() {
  const { pins, isPinned, toggle } = usePins()
  const recents = useRecents()
  const filters = pins.filter((p) => p.kind === 'view')
  const { total: failed } = useJobsPaged(0, 1, 'failed')
  const showAttention = filters.length > 0 || failed > 0

  if (!showAttention && recents.length === 0) return null
  return (
    <>
      {showAttention && (
        <section aria-labelledby="home-attention">
          <h2
            id="home-attention"
            className="mb-3 text-sm font-semibold text-fg"
          >
            Needs your attention
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {filters.map((pin) => (
              <AttentionCard key={pin.key} pin={pin} />
            ))}
            <FailedRunsCard />
          </div>
        </section>
      )}
      {recents.length > 0 && (
        <section aria-labelledby="home-recents">
          <h2 id="home-recents" className="mb-3 text-sm font-semibold text-fg">
            Pick up where you left off
          </h2>
          <ul className="divide-y divide-border-muted rounded-md border border-border">
            {recents.map((r) => {
              const Icon = PIN_ICONS[r.kind]
              const pinned = isPinned(r.key)
              return (
                <li
                  key={r.key}
                  className="flex items-center gap-3 px-4 py-2 text-sm"
                >
                  <Icon
                    size={16}
                    className="shrink-0 text-fg-subtle"
                    aria-hidden="true"
                  />
                  <Link
                    to={r.to}
                    className="min-w-0 truncate font-medium text-accent hover:underline"
                  >
                    {r.label}
                  </Link>
                  {r.context && (
                    <span className="truncate text-xs text-fg-subtle">
                      {r.context}
                    </span>
                  )}
                  <IconButton
                    icon={Star}
                    className={`ml-auto ${pinned ? '!text-accent' : ''}`}
                    aria-label={pinned ? `Unpin ${r.label}` : `Pin ${r.label}`}
                    aria-pressed={pinned}
                    iconProps={{ fill: pinned ? 'currentColor' : 'none' }}
                    onClick={() => toggle(r)}
                  />
                </li>
              )
            })}
          </ul>
        </section>
      )}
    </>
  )
}
