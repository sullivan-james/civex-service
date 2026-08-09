import type { ReactNode } from 'react'

/**
 * Column span out of the 12-column grid. Resolves to the same fraction at
 * every breakpoint (12 = full row, 6 = half, 4 = a third) so labels and
 * controls always land on a shared column edge, and collapses to a single
 * column below the `md` breakpoint.
 */
export type FieldSpan = 4 | 6 | 12

const SPAN_CLASSES: Record<FieldSpan, string> = {
  4: 'col-span-1 md:col-span-2 lg:col-span-4',
  6: 'col-span-1 md:col-span-3 lg:col-span-6',
  12: 'col-span-1 md:col-span-6 lg:col-span-12',
}

export function spanClassName(span: FieldSpan): string {
  return SPAN_CLASSES[span]
}

export interface FormGridProps {
  children: ReactNode
  className?: string
}

/** 12-column form grid. Children (typically `Field`s with a `span`) place
 * themselves via `col-span-*` — never via a hand-picked `w-*` class. */
export function FormGrid({ children, className = '' }: FormGridProps) {
  return (
    <div
      className={`grid grid-cols-1 gap-x-4 gap-y-3 md:grid-cols-6 lg:grid-cols-12 ${className}`}
    >
      {children}
    </div>
  )
}

export interface FormSectionProps {
  title: ReactNode
  description?: ReactNode
  children: ReactNode
}

/** Full-width grouped heading inside a `FormGrid`. Renders as a fragment so
 * its children remain direct grid items of the enclosing `FormGrid`. */
export function FormSection({
  title,
  description,
  children,
}: FormSectionProps) {
  return (
    <>
      <div className="col-span-1 md:col-span-6 lg:col-span-12 flex flex-col gap-0.5 border-t border-border-muted pt-3 first:border-t-0 first:pt-0">
        <h3 className="text-sm font-semibold text-fg">{title}</h3>
        {description && <p className="text-xs text-fg-subtle">{description}</p>}
      </div>
      {children}
    </>
  )
}

export interface FormFooterProps {
  children: ReactNode
  className?: string
}

/** Standard full-width footer row for form actions (save/cancel, etc). */
export function FormFooter({ children, className = '' }: FormFooterProps) {
  return (
    <div
      className={`col-span-1 md:col-span-6 lg:col-span-12 flex items-center justify-end gap-2 ${className}`}
    >
      {children}
    </div>
  )
}
