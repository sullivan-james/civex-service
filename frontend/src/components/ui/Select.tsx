import { forwardRef } from 'react'
import { controlBase, controlBorder, controlSizes, type ControlSize } from './Input'

export interface SelectProps
  extends React.SelectHTMLAttributes<HTMLSelectElement> {
  size?: ControlSize
  invalid?: boolean
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  function Select(
    { size = 'md', invalid = false, className = '', ...props },
    ref,
  ) {
    return (
      <select
        ref={ref}
        className={`${controlBase} ${controlSizes[size]} ${controlBorder(invalid)} cursor-pointer ${className}`}
        {...props}
      />
    )
  },
)
