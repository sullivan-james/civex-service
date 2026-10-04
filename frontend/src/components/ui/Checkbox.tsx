import { forwardRef } from 'react'

export interface CheckboxProps extends React.InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  function Checkbox({ invalid = false, className = '', ...props }, ref) {
    return (
      <input
        ref={ref}
        type="checkbox"
        className={`h-4 w-4 rounded-md border-border accent-accent cursor-pointer focus:outline-none focus:ring-1 ${invalid ? 'focus:ring-danger' : 'focus:ring-accent'} disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
        {...props}
      />
    )
  },
)
