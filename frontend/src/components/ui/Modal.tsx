import {
  createContext,
  useContext,
  useId,
  useLayoutEffect,
  useRef,
  type ReactNode,
} from 'react'

type ModalSize = 'sm' | 'md' | 'lg' | 'xl' | '2xl'

// max-w-2xl covers ordinary form dialogs; xl/2xl exist for the code-editor
// style modals (plugin/workflow editors) that need real width for CodeMirror.
const sizeClasses: Record<ModalSize, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-2xl',
  xl: 'max-w-3xl',
  '2xl': 'max-w-5xl',
}

const ModalTitleContext = createContext<string | null>(null)

interface ModalProps {
  onClose: () => void
  size?: ModalSize
  children: ReactNode
  className?: string
  /** Set false to block Escape and backdrop-click dismissal, e.g. while a
   * confirmation's request is in flight. Defaults to true. */
  dismissible?: boolean
}

/** Accessible modal built on native <dialog>/showModal(), which supplies the
 * focus trap and top-layer stacking for free. Renders only while mounted by
 * the caller (the existing `{open && <Modal>...}` convention across the
 * app) -- mount triggers showModal(), unmount restores focus to whatever was
 * focused beforehand. */
export function Modal({
  onClose,
  size = 'md',
  children,
  className = '',
  dismissible = true,
}: ModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useLayoutEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    const trigger = document.activeElement
    if (!dialog.open) dialog.showModal()
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previousOverflow
      if (trigger instanceof HTMLElement) trigger.focus()
    }
  }, [])

  useLayoutEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    // 'cancel' fires (Escape) before 'close' and is the only one cancelable --
    // blocking it keeps the dialog open without touching the onClose wiring.
    const handleCancel = (e: Event) => {
      if (!dismissible) e.preventDefault()
    }
    dialog.addEventListener('cancel', handleCancel)
    dialog.addEventListener('close', onClose)
    return () => {
      dialog.removeEventListener('cancel', handleCancel)
      dialog.removeEventListener('close', onClose)
    }
  }, [onClose, dismissible])

  return (
    <dialog
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onMouseDown={(e) => {
        if (dismissible && e.target === dialogRef.current)
          dialogRef.current?.close()
      }}
      className="fixed inset-0 m-0 h-full max-h-none w-full max-w-none border-0 bg-transparent p-4 flex items-center justify-center backdrop:bg-overlay-scrim"
    >
      <div
        className={`bg-white rounded-lg border border-border shadow-lg w-full max-h-full flex flex-col ${sizeClasses[size]} ${className}`}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <ModalTitleContext.Provider value={titleId}>
          {children}
        </ModalTitleContext.Provider>
      </div>
    </dialog>
  )
}

export function ModalHeader({
  children,
  onClose,
}: {
  children: ReactNode
  onClose?: () => void
}) {
  const titleId = useContext(ModalTitleContext)
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-4 border-b border-border shrink-0">
      <h2 id={titleId ?? undefined} className="text-base font-semibold text-fg">
        {children}
      </h2>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="text-fg-muted hover:text-fg text-xl leading-none"
        >
          ×
        </button>
      )}
    </div>
  )
}

export function ModalBody({
  children,
  className = '',
  padded = true,
}: {
  children: ReactNode
  className?: string
  /** Set false for edge-to-edge content (e.g. a split-pane file editor)
   * that needs its own internal padding instead of the standard inset. */
  padded?: boolean
}) {
  return (
    <div
      className={`flex-1 min-h-0 overflow-y-auto ${padded ? 'p-5' : ''} ${className}`}
    >
      {children}
    </div>
  )
}

export function ModalFooter({ children }: { children: ReactNode }) {
  return (
    <div className="flex justify-end gap-2 px-5 py-4 border-t border-border shrink-0">
      {children}
    </div>
  )
}
