import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { useDismiss } from '../../hooks/useDismiss'

const GAP = 4
const VIEWPORT_MARGIN = 8

interface PopoverProps {
  /** Element the popover hangs off (a table cell, a button, ...). Clicks on
   * it don't count as "outside", so the trigger can keep its own handlers. */
  anchor: HTMLElement | null
  onClose: () => void
  /** Accessible name for the dialog. */
  label: string
  children: ReactNode
  /** Minimum width in px; defaults to the anchor's own width so a popover
   * under a wide column isn't narrower than the thing it edits. */
  minWidth?: number
  /** Which edge of the anchor the panel lines up with before it is clamped
   * into the viewport. */
  align?: 'left' | 'right'
  /** A `max-w-*` class here replaces the default cap. */
  className?: string
}

/** Anchored floating panel, portalled to <body> so a clipping ancestor
 * (`overflow-x-auto` table wrapper, a scroll container) can't cut it off.
 * Positions under the anchor, flips above when there's no room, tracks
 * scroll/resize, closes on Escape / outside click, and puts focus inside on
 * open and back on the anchor on close. Content-agnostic: give it any
 * children -- a form control, a picker, a short form. */
export function Popover({
  anchor,
  onClose,
  label,
  children,
  minWidth,
  align = 'left',
  className = '',
}: PopoverProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const anchorRef = useRef<HTMLElement | null>(anchor)
  const [pos, setPos] = useState<{
    top: number
    left: number
    minWidth: number
  } | null>(null)

  useLayoutEffect(() => {
    anchorRef.current = anchor
  }, [anchor])

  useDismiss(true, [panelRef, anchorRef], onClose)

  const reposition = useCallback(() => {
    const a = anchorRef.current
    const panel = panelRef.current
    if (!a || !panel) return
    const r = a.getBoundingClientRect()
    const height = panel.offsetHeight
    const width = panel.offsetWidth
    const below = r.bottom + GAP
    const fitsBelow = below + height <= window.innerHeight - VIEWPORT_MARGIN
    const top = fitsBelow
      ? below
      : Math.max(VIEWPORT_MARGIN, r.top - GAP - height)
    const wanted = align === 'right' ? r.right - width : r.left
    const left = Math.min(
      Math.max(VIEWPORT_MARGIN, wanted),
      Math.max(VIEWPORT_MARGIN, window.innerWidth - width - VIEWPORT_MARGIN),
    )
    setPos({ top, left, minWidth: minWidth ?? r.width })
  }, [minWidth, align])

  useLayoutEffect(() => {
    reposition()
    // Capture phase so scrolling *any* ancestor (not just the window) moves us.
    window.addEventListener('scroll', reposition, true)
    window.addEventListener('resize', reposition)
    const observer = new ResizeObserver(reposition)
    if (panelRef.current) observer.observe(panelRef.current)
    return () => {
      window.removeEventListener('scroll', reposition, true)
      window.removeEventListener('resize', reposition)
      observer.disconnect()
    }
  }, [reposition])

  // Focus in on open, back to the anchor on close.
  useLayoutEffect(() => {
    const panel = panelRef.current
    const previous = anchorRef.current
    const first = panel?.querySelector<HTMLElement>(
      'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), a[href]',
    )
    ;(first ?? panel)?.focus()
    return () => previous?.focus()
  }, [])

  return createPortal(
    <div
      ref={panelRef}
      role="dialog"
      aria-label={label}
      tabIndex={-1}
      style={{
        position: 'fixed',
        top: pos?.top ?? 0,
        left: pos?.left ?? 0,
        minWidth: pos?.minWidth,
        // Invisible until measured so it never flashes at 0,0.
        visibility: pos ? 'visible' : 'hidden',
      }}
      className={`z-50 bg-canvas border border-border rounded-md shadow-lg p-3 ${
        /\bmax-w-/.test(className) ? '' : 'max-w-[min(32rem,calc(100vw-1rem))]'
      } ${className}`}
    >
      {children}
    </div>,
    document.body,
  )
}
