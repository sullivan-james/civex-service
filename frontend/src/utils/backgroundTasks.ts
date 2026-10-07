import type { ComponentType, ReactNode } from 'react'

/** Something happening in the background that a person should be able to see
 * wherever they are in the app, and act on. The bottom bar draws any number of
 * these and knows nothing about what they are: a source (file moves, workflow
 * runs, whatever comes next) turns its own state into tasks, and the bar shows
 * them the same way, so a new kind of work needs a source and nothing else. */
export interface BackgroundTask {
  /** Stable, so a task keeps its row as it changes. */
  id: string
  /** `attention` for something that needs a person (paused, waiting on a drive);
   * `info` for work that is simply going on. */
  tone: 'info' | 'attention'
  icon: ComponentType<{
    size?: number
    className?: string
    'aria-hidden'?: boolean | 'true'
  }>
  /** Turn the icon, for work that is going on. */
  spinning?: boolean
  /** What it is, in a few words. */
  title: string
  /** A bar, when how far along it is is known. Without it, no bar is drawn.
   * `label` names it for a screen reader; `count` is shown beside it
   * ("12 of 50 files"), else the percentage is. */
  progress?: { fraction: number; label: string; count?: string }
  /** The particulars: counts, speed, time left. */
  detail?: string
  /** Something muted beside it, such as how many more are waiting. */
  note?: string
  actions?: TaskAction[]
  /** Drawn with the bar, for a dialog one of the actions opens. */
  overlay?: ReactNode
}

/** A button, or -- with `to` -- a link, at the end of a task's row. */
export interface TaskAction {
  label: string
  onClick?: () => void
  /** An address in the app: makes this a link. */
  to?: string
  disabled?: boolean
  variant?: 'default' | 'primary' | 'danger'
}

/** The width of a bar (0 to 100) for a 0 to 1 fraction, kept inside the range. */
export function barPercent(fraction: number): number {
  return Math.max(0, Math.min(100, Math.round(fraction * 100)))
}
