import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { IconButton } from './IconButton'
import { MoreVertical } from './icons'

export interface BreadcrumbItem {
  label: string
  to?: string
}

/** Breadcrumb trail — every item but the last renders as a link; the last
 * is plain text marked `aria-current="page"`. */
export function Breadcrumb({ trail }: { trail: BreadcrumbItem[] }) {
  return (
    <nav
      aria-label="Breadcrumb"
      className="flex items-center gap-2 text-sm text-fg-muted flex-wrap"
    >
      {trail.map((item, i) => {
        const isLast = i === trail.length - 1
        return (
          <span key={i} className="flex items-center gap-2">
            {i > 0 && <span aria-hidden="true">/</span>}
            {!isLast && item.to ? (
              <Link to={item.to} className="hover:text-accent">
                {item.label}
              </Link>
            ) : (
              <span
                className={isLast ? 'text-fg font-medium' : undefined}
                aria-current={isLast ? 'page' : undefined}
              >
                {item.label}
              </span>
            )}
          </span>
        )
      })}
    </nav>
  )
}

export interface PageMenuAction {
  label: string
  onClick: () => void
  variant?: 'default' | 'danger'
  disabled?: boolean
}

/** Overflow menu for a page's secondary actions. */
function PageActionsMenu({ actions }: { actions: PageMenuAction[] }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onPointerDown(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div ref={rootRef} className="relative inline-flex">
      <IconButton
        icon={MoreVertical}
        aria-label="More actions"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
      />
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full mt-1 z-10 min-w-[10rem] bg-canvas border border-border rounded-md shadow-lg py-1"
        >
          {actions.map((a) => (
            <button
              key={a.label}
              type="button"
              role="menuitem"
              disabled={a.disabled}
              onClick={() => {
                setOpen(false)
                a.onClick()
              }}
              className={`w-full text-left px-3 py-2 text-sm disabled:opacity-50 disabled:cursor-not-allowed ${
                a.variant === 'danger'
                  ? 'text-danger hover:bg-danger-subtle'
                  : 'text-fg hover:bg-canvas-subtle'
              }`}
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export interface PageProps {
  breadcrumbs?: BreadcrumbItem[]
  title?: ReactNode
  description?: ReactNode
  action?: ReactNode
  secondaryActions?: PageMenuAction[]
  tabs?: ReactNode
  /** Replaces the title row and content while data is loading. The
   * breadcrumb trail (if any) still renders, so the frame stays put. */
  loading?: ReactNode
  /** Replaces the title row and content on error. */
  error?: ReactNode
  children?: ReactNode
}

/** Structural shell for every routed page: Breadcrumb → title row (title,
 * description, primary action, overflow menu) → optional sub-tabs →
 * content. Owns the vertical rhythm between those regions so pages don't
 * hand-roll their own header markup or top-level spacing. */
export function Page({
  breadcrumbs,
  title,
  description,
  action,
  secondaryActions,
  tabs,
  loading,
  error,
  children,
}: PageProps) {
  const hasTitleRow = !!(
    title ||
    description ||
    action ||
    secondaryActions?.length
  )

  return (
    <div>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <div className="mb-4">
          <Breadcrumb trail={breadcrumbs} />
        </div>
      )}
      {loading ?? error ?? (
        <>
          {hasTitleRow && (
            <div className="mb-6 flex items-start justify-between gap-4">
              <div>
                {title && (
                  <h1 className="text-xl font-semibold text-fg">{title}</h1>
                )}
                {description && (
                  <div className="mt-1 text-sm text-fg-muted">
                    {description}
                  </div>
                )}
              </div>
              {(action || secondaryActions?.length) && (
                <div className="flex items-center gap-2 shrink-0">
                  {action}
                  {secondaryActions && secondaryActions.length > 0 && (
                    <PageActionsMenu actions={secondaryActions} />
                  )}
                </div>
              )}
            </div>
          )}
          {tabs && <div className="mb-4">{tabs}</div>}
          <div className="space-y-6">{children}</div>
        </>
      )}
    </div>
  )
}
