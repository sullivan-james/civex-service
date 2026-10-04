import { useTargetLabel } from '../hooks/useTargetLabel'
import type { NavTarget } from '../utils/pins'

/** A pinned or recent thing's name, live for a record. For lists, where each row
 * can't call the hook itself. */
export function TargetLabel({ target }: { target: NavTarget }) {
  return <>{useTargetLabel(target)}</>
}
