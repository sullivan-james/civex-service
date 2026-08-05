import { forwardRef } from 'react'
import { controlBase, controlBorder, type ControlSize } from './Input'

const sizes: Record<ControlSize, string> = {
  sm: 'px-2.5 py-1.5 text-xs',
  md: 'px-3 py-2 text-sm',
}

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  size?: ControlSize
  invalid?: boolean
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  function Textarea(
    { size = 'md', invalid = false, className = '', ...props },
    ref,
  ) {
    return (
      <textarea
        ref={ref}
        className={`${controlBase} ${sizes[size]} ${controlBorder(invalid)} ${className}`}
        {...props}
      />
    )
  },
)
