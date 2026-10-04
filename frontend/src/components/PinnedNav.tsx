import { NavLink } from 'react-router'
import { useViewCount } from '../hooks/useViewCount'
import { usePins } from '../hooks/usePins'
import { useTargetLabel } from '../hooks/useTargetLabel'
import type { NavTarget } from '../utils/pins'
import { PIN_ICONS } from './pinIcons'
import { IconButton } from './ui/IconButton'
import { Star } from './ui/icons'

/** How many records a pinned filter matches, as a small figure. */
export function PinCount({ target }: { target: NavTarget }) {
  const { count } = useViewCount(target.schema, target.view)
  if (target.kind !== 'view' || count === undefined) return null
  return (
    <span
      className="ml-auto shrink-0 rounded-full bg-canvas-inset px-1.5 text-xs tabular-nums text-fg-muted"
      aria-label={`${count} matching`}
    >
      {count.toLocaleString()}
    </span>
  )
}

function PinnedItem({
  pin,
  collapsed,
  onNavigate,
  onUnpin,
}: {
  pin: NavTarget
  collapsed: boolean
  onNavigate?: () => void
  onUnpin: () => void
}) {
  const Icon = PIN_ICONS[pin.kind]
  const label = useTargetLabel(pin)
  return (
    <div className="group relative flex items-center">
      <NavLink
        to={pin.to}
        onClick={onNavigate}
        title={collapsed ? label : undefined}
        aria-label={collapsed ? label : undefined}
        className={({ isActive }) =>
          `flex min-w-0 flex-1 items-center gap-3 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
            collapsed ? 'justify-center px-0' : ''
          } ${
            isActive
              ? 'bg-accent-subtle text-accent'
              : 'text-fg-muted hover:bg-canvas-inset hover:text-fg'
          }`
        }
      >
        <Icon size={18} className="shrink-0" aria-hidden="true" />
        {!collapsed && (
          <>
            <span className="truncate">{label}</span>
            <PinCount target={pin} />
          </>
        )}
      </NavLink>
      {!collapsed && (
        <IconButton
          icon={Star}
          aria-label={`Unpin ${label}`}
          iconProps={{ fill: 'currentColor' }}
          onClick={onUnpin}
          className="absolute right-1 !bg-canvas-inset !text-accent opacity-0 focus-visible:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100"
        />
      )}
    </div>
  )
}

/** The pinned shortcuts, above the nav groups. Each has a star to unpin; a
 * saved filter carries its live count. */
export function PinnedNav({
  collapsed,
  onNavigate,
}: {
  collapsed: boolean
  onNavigate?: () => void
}) {
  const { pins, toggle } = usePins()
  if (pins.length === 0) return null
  return (
    <div className="mb-2 flex flex-col gap-1" aria-label="Pinned">
      {!collapsed && (
        <div className="px-3 pb-1 text-xs font-semibold uppercase tracking-wider text-fg-subtle">
          Pinned
        </div>
      )}
      {pins.map((pin) => (
        <PinnedItem
          key={pin.key}
          pin={pin}
          collapsed={collapsed}
          onNavigate={onNavigate}
          onUnpin={() => toggle(pin)}
        />
      ))}
      <div className="mx-3 mt-1 border-b border-border-muted" />
    </div>
  )
}
