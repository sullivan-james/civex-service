export type ControlSize = 'sm' | 'md' | 'lg'

export const controlSizes: Record<ControlSize, string> = {
  sm: 'h-8 px-2.5 text-sm',
  md: 'h-9 px-3 text-sm',
  // For the main fields of a form that is the point of the page.
  lg: 'h-11 px-4 text-base',
}

export const controlBase =
  'rounded-md border bg-canvas text-fg placeholder:text-fg-subtle focus:outline-none focus:ring-1 disabled:opacity-50 disabled:cursor-not-allowed'

export const controlBorder = (invalid: boolean | undefined) =>
  invalid
    ? 'border-danger focus:border-danger focus:ring-danger'
    : 'border-border focus:border-accent focus:ring-accent'
