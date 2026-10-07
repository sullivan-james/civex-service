import { barPercent } from '../../utils/backgroundTasks'

/** How far along something is, or how full, as a bar: `fraction` 0 to 1. The
 * one bar in the app (the status bar, moves, uploads, a drive's space), so the
 * same kind of thing looks the same wherever it is shown. `meter` is for how
 * full something is rather than how far a task has got; `warn` colours it as
 * worth a look; `busy` pulses it while the end can't be measured. */
export function ProgressBar({
  fraction,
  label,
  className = 'w-40 sm:w-64',
  meter = false,
  warn = false,
  busy = false,
  thin = false,
  muted = false,
}: {
  fraction: number
  /** What it measures, for a screen reader. */
  label: string
  className?: string
  meter?: boolean
  warn?: boolean
  busy?: boolean
  thin?: boolean
  /** A share that is not the main thing (kept only for history, say). */
  muted?: boolean
}) {
  const pct = barPercent(fraction)
  return (
    <div
      role={meter ? 'meter' : 'progressbar'}
      aria-label={label}
      aria-valuenow={busy ? undefined : pct}
      aria-valuemin={0}
      aria-valuemax={100}
      className={`${thin ? 'h-1.5' : 'h-2'} overflow-hidden rounded-full bg-canvas-inset ${className}`}
    >
      <div
        className={`h-full transition-[width] ${warn ? 'bg-attention' : muted ? 'bg-fg-subtle' : 'bg-accent'} ${busy ? 'animate-pulse' : ''}`}
        style={{ width: `${busy ? 100 : pct}%` }}
      />
    </div>
  )
}
