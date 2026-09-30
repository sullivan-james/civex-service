import { useEffect, useRef, type RefObject } from 'react'

/** Calls `onDismiss` on Escape or on a mousedown outside every element in
 * `refs` -- the one place that "click-outside / Escape closes it" lives, so
 * `Menu`, `Popover` and any future floating UI behave identically. Pass all
 * the elements that count as "inside" (e.g. both the panel and its trigger). */
export function useDismiss(
  open: boolean,
  refs: RefObject<HTMLElement | null>[],
  onDismiss: () => void,
) {
  // Latest callback without re-subscribing listeners on every render.
  const onDismissRef = useRef(onDismiss)
  useEffect(() => {
    onDismissRef.current = onDismiss
  }, [onDismiss])
  const refsRef = useRef(refs)
  useEffect(() => {
    refsRef.current = refs
  }, [refs])

  useEffect(() => {
    if (!open) return
    function onPointerDown(e: MouseEvent) {
      const target = e.target as Node
      if (refsRef.current.some((r) => r.current?.contains(target))) return
      onDismissRef.current()
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onDismissRef.current()
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])
}
