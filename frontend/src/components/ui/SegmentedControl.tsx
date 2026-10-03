import { type ReactNode } from 'react'

export interface SegmentOption<T extends string> {
  value: T
  label: ReactNode
}

/** A short single-choice switch (AND / OR, Light / Dark / System). Every
 * segment is a full-height button; the choice is announced as a radio group. */
export function SegmentedControl<T extends string>({
  label,
  options,
  value,
  onChange,
  size = 'md',
}: {
  label: string
  options: SegmentOption<T>[]
  value: T
  onChange: (next: T) => void
  size?: 'sm' | 'md'
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex overflow-hidden rounded-md border border-border"
    >
      {options.map((opt, i) => {
        const selected = opt.value === value
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(opt.value)}
            className={`${size === 'sm' ? 'h-8' : 'h-9'} cursor-pointer px-3 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent ${
              i > 0 ? 'border-l border-border' : ''
            } ${
              selected
                ? 'bg-accent text-fg-on-emphasis'
                : 'bg-canvas text-fg-muted hover:bg-canvas-subtle hover:text-fg'
            }`}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}
