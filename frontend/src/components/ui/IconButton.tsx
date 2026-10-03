import type { ComponentType } from 'react'
import { Tooltip, type TooltipSide } from './Tooltip'

type Variant = 'default' | 'danger' | 'subtle'
type Size = 'xs' | 'sm' | 'md'

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

// Never below the 32px control height; the icon stays 16px and the extra
// space around it is padding, so the whole square is the click target.
const sizes: Record<Size, string> = {
  // Only inside something that is itself a 32px+ target (a chip's remove).
  xs: 'h-6 w-6',
  sm: 'h-8 w-8',
  md: 'h-9 w-9',
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
  const button = (
    <button
      type="button"
      aria-label={ariaLabel}
      disabled={disabled}
      className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    >
      <Icon size={16} className="shrink-0" aria-hidden="true" {...iconProps} />
    </button>
  )

  if (disabled) return <span className="inline-flex">{button}</span>
  return (
    <Tooltip content={ariaLabel} side={tooltipSide}>
      {button}
    </Tooltip>
  )
}
