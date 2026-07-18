import { type ReactNode } from 'react'

type Variant = 'default' | 'accent' | 'success' | 'danger'

const variants: Record<Variant, string> = {
  default: 'bg-[#818b9833] text-[#656d76] border-[#818b9833]',
  accent: 'bg-[#ddf4ff] text-[#0969da] border-[#54aeff66]',
  success: 'bg-[#dafbe1] text-[#1a7f37] border-[#4ac26b66]',
  danger: 'bg-[#ffebe9] text-[#d1242f] border-[#ffd7d5]',
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
