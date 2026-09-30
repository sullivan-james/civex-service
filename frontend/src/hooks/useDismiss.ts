import { useEffect, type RefObject } from 'react'

/** Calls `close` on an outside pointer-down or Escape while `open` -- the
 * dismissal every click-to-open panel (menus, popovers) shares. */
export function useDismiss(
  ref: RefObject<HTMLElement | null>,
  open: boolean,
  close: () => void,
) {
  useEffect(() => {
    if (!open) return
    function onPointerDown(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) close()
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') close()
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [ref, open, close])
}
