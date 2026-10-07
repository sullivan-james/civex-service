import { useCallback, useLayoutEffect, useState, type RefObject } from 'react'

const GAP = 4
const VIEWPORT_MARGIN = 8

export interface AnchoredPosition {
  top: number
  left: number
  /** The anchor's own width, for panels that shouldn't be narrower. */
  anchorWidth: number
  /** The most the panel may take before it scrolls inside itself. */
  maxHeight: number
}

/** Where a floating panel goes beside its anchor, in window coordinates (the
 * panel is `position: fixed`, portalled to <body>, so neither a clipping
 * ancestor cuts it off nor does it stretch the page). Under the anchor, or above
 * it when there is more room there; lined up with its `align` edge and kept
 * inside the window; and never taller than the room on that side, so a long
 * panel scrolls inside itself. Follows any scroll and resize. The one rule for
 * `Popover` and `Menu`. Null until measured. */
export function useAnchoredPosition(
  anchorRef: RefObject<HTMLElement | null>,
  panelRef: RefObject<HTMLElement | null>,
  align: 'left' | 'right' = 'left',
  open = true,
): AnchoredPosition | null {
  const [pos, setPos] = useState<AnchoredPosition | null>(null)

  const reposition = useCallback(() => {
    const anchor = anchorRef.current
    const panel = panelRef.current
    if (!anchor || !panel) return
    const r = anchor.getBoundingClientRect()
    const height = panel.scrollHeight
    const width = panel.offsetWidth
    const roomBelow = window.innerHeight - VIEWPORT_MARGIN - (r.bottom + GAP)
    const roomAbove = r.top - GAP - VIEWPORT_MARGIN
    const below = height <= roomBelow || roomBelow >= roomAbove
    const maxHeight = Math.max(0, below ? roomBelow : roomAbove)
    const shown = Math.min(height, maxHeight)
    const top = below ? r.bottom + GAP : r.top - GAP - shown
    const wanted = align === 'right' ? r.right - width : r.left
    const left = Math.min(
      Math.max(VIEWPORT_MARGIN, wanted),
      Math.max(VIEWPORT_MARGIN, window.innerWidth - width - VIEWPORT_MARGIN),
    )
    const next = { top, left, anchorWidth: r.width, maxHeight }
    // Unchanged (a scroll elsewhere, a resize that moved nothing): no render.
    setPos((prev) =>
      prev &&
      prev.top === next.top &&
      prev.left === next.left &&
      prev.anchorWidth === next.anchorWidth &&
      prev.maxHeight === next.maxHeight
        ? prev
        : next,
    )
  }, [anchorRef, panelRef, align])

  useLayoutEffect(() => {
    if (!open) return
    reposition() // measured before it paints, so it never shows out of place
    // Capture phase so scrolling *any* ancestor (not just the window) moves it.
    window.addEventListener('scroll', reposition, true)
    window.addEventListener('resize', reposition)
    const observer = new ResizeObserver(reposition)
    if (panelRef.current) observer.observe(panelRef.current)
    return () => {
      window.removeEventListener('scroll', reposition, true)
      window.removeEventListener('resize', reposition)
      observer.disconnect()
    }
  }, [reposition, open, panelRef])

  return open ? pos : null
}
