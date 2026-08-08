type Variant = 'primary' | 'default' | 'danger'

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: 'sm' | 'md'
}

const base =
  'inline-flex items-center gap-2 font-medium rounded-md border cursor-pointer transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50 disabled:cursor-not-allowed'

const variants: Record<Variant, string> = {
  primary:
    'bg-success-emphasis hover:bg-success border-[rgba(31,35,40,0.15)] text-fg-on-emphasis',
  default: 'bg-canvas-subtle hover:bg-canvas-inset border-border text-fg',
  danger: 'bg-canvas-subtle hover:bg-danger-subtle border-border text-danger',
}

const sizes = { sm: 'h-8 px-3 text-xs', md: 'h-9 px-4 text-sm' }

export function Button({
  variant = 'default',
  size = 'md',
  className = '',
  ...props
}: ButtonProps) {
  return (
    <button
      className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    />
  )
}
