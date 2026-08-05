import { type ReactNode } from 'react'

type Variant = 'default' | 'accent' | 'success' | 'danger'

const variants: Record<Variant, string> = {
  default: 'bg-neutral-subtle text-fg-muted border-neutral-subtle',
  accent: 'bg-accent-subtle text-accent border-accent-muted',
  success: 'bg-success-subtle text-success border-success-muted',
  danger: 'bg-danger-subtle text-danger border-danger-subtle-border',
}

export function Badge({
  children,
  variant = 'default',
  className = '',
}: {
  children: ReactNode
  variant?: Variant
  className?: string
}) {
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 text-xs font-medium rounded-full border ${variants[variant]} ${className}`}
    >
      {children}
    </span>
  )
}
