import { StepBadge, type StepState } from './StepBadge'

export interface StepperStep {
  label: string
}

/** Horizontal wizard step indicator: numbered badges connected by a line,
 * steps before `activeIndex` marked done (check), current one highlighted. */
export function Stepper({
  steps,
  activeIndex,
}: {
  steps: StepperStep[]
  activeIndex: number
}) {
  return (
    <ol className="flex items-center">
      {steps.map((step, i) => {
        const state: StepState =
          i < activeIndex ? 'done' : i === activeIndex ? 'current' : 'upcoming'
        return (
          <li
            key={step.label}
            className={`flex items-center ${i < steps.length - 1 ? 'flex-1' : ''}`}
          >
            <div className="flex items-center gap-2">
              <StepBadge index={i + 1} state={state} />
              <span
                className={`text-sm font-medium whitespace-nowrap ${
                  state === 'upcoming' ? 'text-fg-subtle' : 'text-fg'
                }`}
              >
                {step.label}
              </span>
            </div>
            {i < steps.length - 1 && (
              <div
                className={`mx-3 h-px flex-1 ${i < activeIndex ? 'bg-accent' : 'bg-border'}`}
                aria-hidden="true"
              />
            )}
          </li>
        )
      })}
    </ol>
  )
}
