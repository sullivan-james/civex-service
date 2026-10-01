import { usePins } from '../../hooks/usePins'
import type { NavTarget } from '../../utils/pins'
import { IconButton } from './IconButton'
import { Star } from './icons'

/** A star that pins `target` to the nav and Home (filled while pinned).
 * Pins live in this browser. */
export function PinButton({
  target,
  noun,
  size,
}: {
  target: NavTarget
  /** What is being pinned, for the label: "record", "view", … */
  noun: string
  size?: 'sm' | 'md'
}) {
  const { isPinned, toggle } = usePins()
  const pinned = isPinned(target.key)
  return (
    <IconButton
      icon={Star}
      size={size}
      aria-label={pinned ? `Unpin this ${noun}` : `Pin this ${noun}`}
      aria-pressed={pinned}
      onClick={() => toggle(target)}
      iconProps={{ fill: pinned ? 'currentColor' : 'none' }}
      className={pinned ? '!text-accent' : ''}
    />
  )
}
