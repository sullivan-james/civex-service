import { Link, type LinkProps } from 'react-router'

type Variant =
  'primary' | 'default' | 'danger' | 'ghost' | 'link' | 'nav' | 'navActive'
type Size = 'sm' | 'md'

interface CommonProps {
  variant?: Variant
  size?: Size
}

type ButtonAsButton = CommonProps &
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    to?: undefined
    href?: undefined
  }
type ButtonAsLink = CommonProps &
  Omit<LinkProps, 'className'> & { className?: string; href?: undefined }
/** A plain anchor, for downloads and links off the app. */
type ButtonAsAnchor = CommonProps &
  React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string
    to?: undefined
  }

export type ButtonProps = ButtonAsButton | ButtonAsLink | ButtonAsAnchor

const base =
  'inline-flex items-center justify-center gap-2 font-medium rounded-md border cursor-pointer transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50 disabled:cursor-not-allowed'

const variants: Record<Variant, string> = {
  primary:
    'bg-accent hover:bg-accent-emphasis border-accent text-fg-on-emphasis',
  default: 'bg-canvas-subtle hover:bg-canvas-inset border-border text-fg',
  danger: 'bg-canvas-subtle hover:bg-danger-subtle border-border text-danger',
  // Toolbar / low-emphasis actions: no chrome until hovered.
  ghost:
    'bg-transparent hover:bg-canvas-inset border-transparent text-fg-muted hover:text-fg',
  // Reads as a link but keeps the full button hit area.
  link: 'bg-transparent hover:bg-accent-subtle border-transparent text-accent',
  // On the always-dark top bar.
  nav: 'bg-nav-surface hover:bg-nav-surface-hover border-nav-border text-nav-fg-muted hover:text-nav-fg',
  navActive: 'bg-accent border-accent text-fg-on-emphasis',
}

// Heights match the shared control heights (`--control-height-sm|md`) so a
// button sits level with an input beside it.
const sizes: Record<Size, string> = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-9 px-4 text-sm',
}

/** The one button. Pass `to` to render a router link with the same look, so
 * navigation never needs a `<Link>` wrapped around a `<button>`. */
export function Button(props: ButtonProps) {
  const { variant = 'default', size = 'md', className = '' } = props
  const classes = `${base} ${variants[variant]} ${sizes[size]} ${className}`

  if (props.href !== undefined) {
    const {
      variant: _v,
      size: _s,
      className: _c,
      to: _t,
      ...anchorProps
    } = props
    return <a className={classes} {...anchorProps} />
  }
  if (props.to !== undefined) {
    const { variant: _v, size: _s, className: _c, ...linkProps } = props
    return <Link className={classes} {...linkProps} />
  }
  const { variant: _v, size: _s, className: _c, to: _t, ...buttonProps } = props
  return <button className={classes} {...buttonProps} />
}
