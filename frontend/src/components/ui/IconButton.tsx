import { useId, useState, type ComponentType } from 'react'

type Variant = 'default' | 'danger' | 'subtle'
type Size = 'sm' | 'md'
type TooltipSide = 'top' | 'bottom'

interface IconButtonProps extends Omit<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  'title'
> {
  icon: ComponentType<Record<string, unknown>>
  'aria-label': string
  variant?: Variant
  size?: Size
  tooltipSide?: TooltipSide
  iconProps?: Record<string, unknown>
}

const base =
  'inline-flex items-center justify-center rounded-md border border-transparent cursor-pointer transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none'

const variants: Record<Variant, string> = {
  default: 'text-fg-muted hover:text-fg hover:bg-canvas-inset',
  danger: 'text-fg-muted hover:text-danger hover:bg-danger-subtle',
  subtle: 'text-fg-subtle hover:text-fg-muted hover:bg-canvas-inset',
}

// 28px is the WCAG 2.5.8 minimum hit area; the icon itself stays 16px and
// the extra space around it comes from padding, not a bigger glyph.
const sizes: Record<Size, string> = {
  sm: 'h-7 w-7',
  md: 'h-8 w-8',
}

const tooltipSides: Record<TooltipSide, string> = {
  top: 'bottom-full left-1/2 -translate-x-1/2 mb-1.5',
  bottom: 'top-full left-1/2 -translate-x-1/2 mt-1.5',
}

export function IconButton({
  icon: Icon,
  'aria-label': ariaLabel,
  variant = 'default',
  size = 'sm',
  tooltipSide = 'top',
  className = '',
  disabled,
  iconProps,
  ...props
}: IconButtonProps) {
  const [showTooltip, setShowTooltip] = useState(false)
  const tooltipId = useId()

  const hide = () => setShowTooltip(false)

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        aria-label={ariaLabel}
        aria-describedby={showTooltip ? tooltipId : undefined}
        disabled={disabled}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={hide}
        onFocus={() => setShowTooltip(true)}
        onBlur={hide}
        className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}
        {...props}
      >
        <Icon
          size={16}
          className="shrink-0"
          aria-hidden="true"
          {...iconProps}
        />
      </button>
      {showTooltip && !disabled && (
        <span
          id={tooltipId}
          role="tooltip"
          className={`pointer-events-none absolute z-10 whitespace-nowrap rounded-md bg-fg px-2 py-1 text-xs font-medium text-canvas shadow-sm ${tooltipSides[tooltipSide]}`}
        >
          {ariaLabel}
        </span>
      )}
    </span>
  )
}
