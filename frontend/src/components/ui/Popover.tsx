import { useLayoutEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useAnchoredPosition } from '../../hooks/useAnchoredPosition'
import { useDismiss } from '../../hooks/useDismiss'

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
  useLayoutEffect(() => {
    anchorRef.current = anchor
  }, [anchor])

  useDismiss(true, [panelRef, anchorRef], onClose)
  const pos = useAnchoredPosition(anchorRef, panelRef, align)

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
        minWidth: minWidth ?? pos?.anchorWidth,
        maxHeight: pos?.maxHeight,
        // Invisible until measured so it never flashes at 0,0.
        visibility: pos ? 'visible' : 'hidden',
      }}
      className={`z-50 overflow-y-auto bg-canvas border border-border rounded-md shadow-lg p-3 ${
        /\bmax-w-/.test(className) ? '' : 'max-w-[min(32rem,calc(100vw-1rem))]'
      } ${className}`}
    >
      {children}
    </div>,
    document.body,
  )
}
