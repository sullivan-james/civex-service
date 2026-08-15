import { useEffect, useRef, type RefObject } from 'react'

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

function getFocusable(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  ).filter((el) => el.offsetParent !== null)
}

// Marks every element outside `root`'s ancestor chain (up to <body>) as
// inert, so background content is unreachable by Tab and hidden from
// assistive tech while the overlay is open -- the manual equivalent of what
// a native <dialog>'s showModal() gives Modal.tsx for free.
function setSiblingsInert(root: HTMLElement, inert: boolean) {
  let node: HTMLElement | null = root
  while (node && node !== document.body) {
    const parent: HTMLElement | null = node.parentElement
    if (!parent) break
    for (const sibling of Array.from(parent.children)) {
      if (sibling !== node && sibling instanceof HTMLElement) {
        sibling.inert = inert
      }
    }
    node = parent
  }
}

interface UseDialogA11yOptions {
  open: boolean
  onClose: () => void
  /** Outermost element of the overlay's own subtree (backdrop + panel, if
   * both exist) -- everything outside its ancestor chain is made inert. */
  rootRef: RefObject<HTMLElement | null>
  /** The dialog panel itself, used for initial focus and as the focus-trap
   * boundary. Defaults to `rootRef` when the overlay has no separate
   * backdrop element. */
  dialogRef?: RefObject<HTMLElement | null>
}

/** Focus trap + Escape-to-close + focus restoration + background inertness
 * for hand-rolled overlays that can't sit on the native <dialog>-based
 * `Modal` primitive (e.g. off-canvas drawers, full-screen panels). */
export function useDialogA11y({
  open,
  onClose,
  rootRef,
  dialogRef,
}: UseDialogA11yOptions) {
  const triggerRef = useRef<Element | null>(null)
  // Keydown handler always calls the latest onClose without needing it in
  // the effect's deps -- this effect must only re-run when `open` flips, not
  // on every parent re-render that hands down a new onClose closure
  // (otherwise focus would jump back to the first control mid-interaction).
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    const root = rootRef.current
    const maybeDialog = dialogRef?.current ?? root
    if (!open || !root || !maybeDialog) return
    const dialog = maybeDialog

    triggerRef.current = document.activeElement
    const focusable = getFocusable(dialog)
    ;(focusable[0] ?? dialog).focus()

    setSiblingsInert(root, true)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        onCloseRef.current()
        return
      }
      if (e.key !== 'Tab') return
      const items = getFocusable(dialog)
      if (items.length === 0) {
        e.preventDefault()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)

    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
      setSiblingsInert(root, false)
      if (triggerRef.current instanceof HTMLElement) triggerRef.current.focus()
    }
  }, [open, rootRef, dialogRef])
}
