import { Check } from './icons'

export type StepState = 'done' | 'current' | 'upcoming'

const stateClasses: Record<StepState, string> = {
  done: 'bg-accent border-accent text-fg-on-emphasis',
  current: 'bg-accent-subtle border-accent text-accent',
  upcoming: 'bg-canvas border-border text-fg-subtle',
}

export function StepBadge({
  index,
  state,
}: {
  /** 1-based step number shown when state isn't 'done'. */
  index: number
  state: StepState
}) {
  return (
    <span
      className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${stateClasses[state]}`}
    >
      {state === 'done' ? <Check size={14} aria-hidden="true" /> : index}
    </span>
  )
}
