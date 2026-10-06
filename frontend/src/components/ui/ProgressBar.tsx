import { barPercent } from '../../utils/backgroundTasks'

/** How far along something is, as a bar: `fraction` 0 to 1. The one bar in the
 * app (the status bar and the pages that show the same work use it), so the
 * same work looks the same wherever it is shown. */
export function ProgressBar({
  fraction,
  label,
  className = 'w-40 sm:w-64',
}: {
  fraction: number
  /** What it measures, for a screen reader. */
  label: string
  className?: string
}) {
  const pct = barPercent(fraction)
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      className={`h-2 overflow-hidden rounded-full bg-canvas-inset ${className}`}
    >
      <div
        className="h-full bg-accent transition-[width]"
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}
