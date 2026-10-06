import { type ButtonHTMLAttributes, type ReactNode } from 'react'
import { X } from './icons'

/** A small pill: a toggle (`selected` + `onClick`), a plain label, or a
 * removable value (`onRemove`). The whole pill is the click target. */
export function Chip({
  children,
  selected,
  onClick,
  onRemove,
  removeLabel = 'Remove',
  dashed = false,
  warning = false,
  size = 'md',
  className = '',
  ...buttonProps
}: Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onClick' | 'children'> & {
  children: ReactNode
  /** Makes the chip a toggle button with this state. */
  selected?: boolean
  onClick?: () => void
  onRemove?: () => void
  removeLabel?: string
  /** An "add" affordance rather than a value. */
  dashed?: boolean
  /** Something needs attention (an unreachable volume). */
  warning?: boolean
  /** `lg` for a choice that is the point of the form. */
  size?: 'md' | 'lg'
  className?: string
}) {
  const tone = warning
    ? 'border-attention-muted bg-attention-subtle text-attention'
    : dashed
      ? 'border-dashed border-border-strong text-fg-muted hover:border-accent hover:text-accent'
      : selected
        ? 'border-accent bg-accent text-fg-on-emphasis'
        : onClick
          ? 'border-border bg-canvas text-fg hover:bg-canvas-inset'
          : 'border-accent-muted bg-accent-subtle text-accent'
  const dims = size === 'lg' ? 'h-10 px-4 text-sm' : 'h-8 px-3 text-sm'
  const base = `inline-flex ${dims} items-center gap-1.5 rounded-full border ${tone} ${className}`

  if (onClick)
    return (
      <button
        type="button"
        aria-pressed={selected === undefined ? undefined : selected}
        {...buttonProps}
        onClick={onClick}
        className={`${base} cursor-pointer transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent`}
      >
        {children}
      </button>
    )
  return (
    <span className={`${base} ${onRemove ? 'pr-1' : ''}`}>
      {children}
      {onRemove && (
        <button
          type="button"
          aria-label={removeLabel}
          onClick={onRemove}
          className="inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded-full hover:bg-accent-subtle-border focus-visible:outline-2 focus-visible:outline-accent"
        >
          <X size={12} aria-hidden="true" />
        </button>
      )}
    </span>
  )
}
