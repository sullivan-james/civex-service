import { type ButtonHTMLAttributes } from 'react'

/** A full-width row you click: a search result, a history entry, a tree item.
 * Left-aligned, at least 36px tall, with the hover / active / selected look
 * every list in the app shares. */
export function ListButton({
  active = false,
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  /** Highlighted: keyboard-active option or the current item. */
  active?: boolean
}) {
  return (
    <button
      type="button"
      className={`block min-h-9 w-full cursor-pointer px-3 py-2 text-left text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent disabled:cursor-default disabled:opacity-50 ${
        active ? 'bg-accent-subtle' : 'hover:bg-canvas-subtle'
      } ${className}`}
      {...props}
    />
  )
}
