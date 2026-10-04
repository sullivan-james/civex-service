import { type ReactNode } from 'react'
import { Link } from 'react-router'
import { useDocumentTitle } from '../../hooks/useDocumentTitle'
import { pageTitleParts } from '../../utils/documentTitle'
import { IconButton } from './IconButton'
import { Menu } from './Menu'
import { InfoTip } from './Tooltip'
import { ChevronRight, MoreVertical } from './icons'

export interface BreadcrumbItem {
  label: string
  to?: string
  /** What kind of thing this is (e.g. a record's schema), shown small and
   * muted before the label. */
  kind?: string
}

function Kind({ kind }: { kind?: string }) {
  if (!kind) return null
  return (
    <span className="mr-1.5 text-xs font-normal text-fg-subtle">{kind}</span>
  )
}

/** Breadcrumb trail — every item but the last renders as a link; the last
 * is plain text marked `aria-current="page"`. */
export function Breadcrumb({ trail }: { trail: BreadcrumbItem[] }) {
  return (
    <nav
      aria-label="Breadcrumb"
      className="flex items-center gap-1 text-base flex-wrap"
    >
      {trail.map((item, i) => {
        const isLast = i === trail.length - 1
        return (
          <span key={i} className="flex items-center gap-1 min-w-0">
            {i > 0 && (
              <ChevronRight
                size={16}
                className="text-fg-subtle shrink-0"
                aria-hidden="true"
              />
            )}
            {!isLast && item.to ? (
              <Link
                to={item.to}
                className="rounded-md px-2 py-1 font-medium text-accent hover:bg-accent-subtle hover:underline"
              >
                <Kind kind={item.kind} />
                {item.label}
              </Link>
            ) : (
              <span
                className={
                  isLast
                    ? 'px-2 py-1 font-semibold text-fg truncate'
                    : 'px-2 py-1 text-fg-muted'
                }
                aria-current={isLast ? 'page' : undefined}
              >
                <Kind kind={item.kind} />
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
  return (
    <Menu
      items={actions}
      trigger={({ open, toggle }) => (
        <IconButton
          icon={MoreVertical}
          aria-label="More actions"
          onClick={toggle}
          aria-expanded={open}
          aria-haspopup="menu"
        />
      )}
    />
  )
}

export interface PageProps {
  breadcrumbs?: BreadcrumbItem[]
  title?: ReactNode
  /** Explanation of the page, shown as a tooltip beside the title. */
  info?: ReactNode
  /** Facts about the thing the page shows (ids, dates, status), under the
   * title. Not for explaining the page: that is `info`. */
  meta?: ReactNode
  action?: ReactNode
  secondaryActions?: PageMenuAction[]
  tabs?: ReactNode
  /** Replaces the title row and content while data is loading. The
   * breadcrumb trail (if any) still renders, so the frame stays put. */
  loading?: ReactNode
  /** Replaces the title row and content on error. */
  error?: ReactNode
  /** What the browser tab says, most specific first, when the title and trail
   * don't say it (a page with several sections of its own). Otherwise it is
   * made from the title and the breadcrumb trail: the current item, then what
   * it sits inside. */
  documentTitle?: string[]
  children?: ReactNode
}

/** Structural shell for every routed page: Breadcrumb → title row (title,
 * description, primary action, overflow menu) → optional sub-tabs →
 * content. Owns the vertical rhythm between those regions so pages don't
 * hand-roll their own header markup or top-level spacing. */
export function Page({
  breadcrumbs,
  title,
  info,
  meta,
  action,
  secondaryActions,
  tabs,
  loading,
  error,
  documentTitle,
  children,
}: PageProps) {
  useDocumentTitle(documentTitle ?? pageTitleParts(title, breadcrumbs))
  const hasTitleRow = !!(title || meta || action || secondaryActions?.length)

  return (
    <div>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <div className="mb-4 -ml-2">
          <Breadcrumb trail={breadcrumbs} />
        </div>
      )}
      {loading ?? error ?? (
        <>
          {hasTitleRow && (
            <div className="mb-6 flex items-start justify-between gap-4">
              <div>
                {title && (
                  <h1 className="flex items-center gap-1 text-xl font-semibold text-fg">
                    {title}
                    {info && <InfoTip side="bottom">{info}</InfoTip>}
                  </h1>
                )}
                {meta && (
                  <div className="mt-1 text-sm text-fg-muted">{meta}</div>
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
