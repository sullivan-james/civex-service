import { cloneElement, isValidElement, useId } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { spanClassName, type FieldSpan } from './FormGrid'

export interface FieldProps {
  label: ReactNode
  hint?: ReactNode
  error?: ReactNode
  required?: boolean
  /** 'stack' (default) puts the label above the control; 'inline' puts the
   * control first with the label as a trailing caption (e.g. checkboxes). */
  layout?: 'stack' | 'inline'
  /** Column span out of 12 when placed inside a `FormGrid`. Omit outside a
   * form grid — width should never come from a `w-*` class. */
  span?: FieldSpan
  className?: string
  children: ReactElement
}

export function Field({
  label,
  hint,
  error,
  required = false,
  layout = 'stack',
  span,
  className = '',
  children,
}: FieldProps) {
  const generatedId = useId()
  const childProps = isValidElement(children)
    ? (children.props as Record<string, unknown>)
    : {}
  const controlId = (childProps.id as string | undefined) ?? generatedId
  const hintId = hint ? `${generatedId}-hint` : undefined
  const errorId = error ? `${generatedId}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined

  const controlOverrides: Record<string, unknown> = { id: controlId }
  if (describedBy) {
    controlOverrides['aria-describedby'] = childProps['aria-describedby']
      ? `${childProps['aria-describedby']} ${describedBy}`
      : describedBy
  }
  if (error) controlOverrides['aria-invalid'] = true

  const control = isValidElement(children)
    ? cloneElement(children, controlOverrides)
    : children

  const requiredMark = required && (
    <span className="text-danger" aria-label="required">
      *
    </span>
  )

  const labelNode =
    layout === 'inline' ? (
      <label
        htmlFor={controlId}
        className="flex items-center gap-2 text-sm text-fg cursor-pointer select-none"
      >
        {control}
        <span>
          {label}
          {requiredMark}
        </span>
      </label>
    ) : (
      <label htmlFor={controlId} className="text-xs font-medium text-fg-muted">
        {label}
        {requiredMark}
      </label>
    )

  return (
    <div
      className={`flex flex-col gap-1 ${span ? spanClassName(span) : ''} ${className}`}
    >
      {labelNode}
      {layout === 'stack' && control}
      {hint && (
        <p id={hintId} className="text-xs text-fg-subtle">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  )
}
