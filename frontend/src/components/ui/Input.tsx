import { forwardRef } from 'react'
import {
  controlBase,
  controlBorder,
  controlSizes,
  type ControlSize,
} from './controlStyles'

export interface InputProps extends Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  'size'
> {
  size?: ControlSize
  invalid?: boolean
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { size = 'md', invalid = false, className = '', ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      className={`${controlBase} ${controlSizes[size]} ${controlBorder(invalid)} ${className}`}
      {...props}
    />
  )
})
