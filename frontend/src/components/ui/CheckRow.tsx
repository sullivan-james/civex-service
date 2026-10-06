import type { ReactNode } from 'react'
import { Checkbox } from './Checkbox'
import { InfoTip } from './Tooltip'

/** A checkbox that is the whole row: a big target with a title, highlighted when
 * on, and showing its own settings (`children`) only while it is. For choices a
 * person should see at a glance (what goes in an export), where a lone box beside
 * small text is too easy to miss. The label spans the row, so a click anywhere on
 * it toggles.
 *
 * Roomy (the default) puts a line of explanation under the title and the settings
 * underneath. `compact` is one slim row: the explanation is an info tip beside the
 * title and the settings sit on the same row, for lists of several choices. */
export function CheckRow({
  checked,
  onChange,
  title,
  description,
  disabled = false,
  compact = false,
  className = '',
  children,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  /** Also the accessible name of the checkbox. */
  title: string
  description?: ReactNode
  disabled?: boolean
  compact?: boolean
  /** To size the row (a compact row can shrink to fit with `w-auto`). */
  className?: string
  /** Settings for the choice, shown while it is on. */
  children?: ReactNode
}) {
  const tone = checked
    ? 'border-accent bg-accent-subtle'
    : 'border-border bg-canvas hover:bg-canvas-subtle'
  const cursor = disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'

  if (compact)
    return (
      <div
        className={`rounded-md border transition-colors ${tone} ${className}`}
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-1.5">
          <label className={`flex min-w-0 flex-1 items-center gap-2 ${cursor}`}>
            <Checkbox
              checked={checked}
              disabled={disabled}
              onChange={(e) => onChange(e.target.checked)}
              aria-label={title}
              className="h-4 w-4 shrink-0"
            />
            <span className="text-sm font-medium text-fg">{title}</span>
            {description && <InfoTip>{description}</InfoTip>}
          </label>
          {checked && children}
        </div>
      </div>
    )

  return (
    <div className={`rounded-lg border transition-colors ${tone} ${className}`}>
      <label className={`flex items-start gap-3 p-4 ${cursor}`}>
        <Checkbox
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
          aria-label={title}
          className="mt-0.5 h-5 w-5 shrink-0"
        />
        <span className="min-w-0 flex-1">
          <span className="block text-base font-medium text-fg">{title}</span>
          {description && (
            <span className="mt-0.5 block text-sm text-fg-muted">
              {description}
            </span>
          )}
        </span>
      </label>
      {checked && children && (
        <div className="border-t border-accent-muted px-4 pb-4 pt-3">
          {children}
        </div>
      )}
    </div>
  )
}
