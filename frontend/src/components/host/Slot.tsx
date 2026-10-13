import { Component, type ReactNode } from 'react'
import type { SlotName } from '../../utils/slots'
import { useSlot } from '../../hooks/useSlot'

/** One extension's component that failed draws nothing and says so in the
 * console: an extension never takes a page down with it. */
class Contained extends Component<
  { id: string; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: unknown) {
    console.error(`civex extension "${this.props.id}" failed to draw`, error)
  }

  render() {
    return this.state.failed ? null : this.props.children
  }
}

/** Draws whatever a host's extensions registered in `name` (`utils/slots`),
 * with `props`; nothing at all when none did, which is always so on a local
 * civex. */
export function Slot({
  name,
  props = {},
}: {
  name: SlotName
  props?: Record<string, unknown>
}) {
  const entries = useSlot(name)
  if (entries.length === 0) return null
  return (
    <>
      {entries.map(({ id, Component: Drawn }) => (
        <Contained key={id} id={id}>
          <Drawn {...props} />
        </Contained>
      ))}
    </>
  )
}

/** One registered entry of `name` by its id (a Settings section of its own),
 * or `fallback` when there is none (yet: extensions load after the app). */
export function SlotItem({
  name,
  id,
  fallback = null,
}: {
  name: SlotName
  id: string
  fallback?: ReactNode
}) {
  const entry = useSlot(name).find((e) => e.id === id)
  if (!entry) return <>{fallback}</>
  const Drawn = entry.Component
  return (
    <Contained key={entry.id} id={entry.id}>
      <Drawn />
    </Contained>
  )
}
