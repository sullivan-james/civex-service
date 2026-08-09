import { useEffect, useRef, useState } from 'react'
import { Check, X, XCircle, Info } from './icons'

export type ToastVariant = 'success' | 'error' | 'info'

export interface ToastAction {
  label: string
  onClick: () => void
}

export interface ToastData {
  id: number
  message: string
  variant: ToastVariant
  action?: ToastAction
  /** ms until auto-dismiss, or null to persist until manually dismissed. */
  duration: number | null
}

const variantStyles: Record<ToastVariant, string> = {
  success: 'bg-success-subtle border-success-muted text-success',
  error: 'bg-danger-subtle border-danger-subtle-border text-danger',
  info: 'bg-accent-subtle border-accent-muted text-accent',
}

const variantIcons: Record<ToastVariant, typeof Check> = {
  success: Check,
  error: XCircle,
  info: Info,
}

export function Toast({
  toast,
  onDismiss,
}: {
  toast: ToastData
  onDismiss: (id: number) => void
}) {
  const [paused, setPaused] = useState(false)
  // Tracks time left across pause/resume cycles instead of restarting the
  // countdown from the full duration every time the pointer leaves.
  const remainingRef = useRef(toast.duration ?? 0)
  const startedAtRef = useRef(0)

  useEffect(() => {
    if (toast.duration == null || paused) return
    startedAtRef.current = Date.now()
    const timer = setTimeout(() => onDismiss(toast.id), remainingRef.current)
    return () => {
      clearTimeout(timer)
      remainingRef.current -= Date.now() - startedAtRef.current
    }
  }, [paused, toast.duration, toast.id, onDismiss])

  const Icon = variantIcons[toast.variant]

  return (
    <div
      role={toast.variant === 'error' ? 'alert' : 'status'}
      aria-live={toast.variant === 'error' ? 'assertive' : 'polite'}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      className={`flex items-start gap-2 rounded-lg border shadow-lg px-4 py-3 text-sm ${variantStyles[toast.variant]}`}
    >
      <Icon size={16} className="mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="break-words">{toast.message}</p>
        {toast.action && (
          <button
            onClick={() => {
              toast.action!.onClick()
              onDismiss(toast.id)
            }}
            className="mt-1 font-medium underline underline-offset-2 hover:no-underline"
          >
            {toast.action.label}
          </button>
        )}
      </div>
      <button
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss notification"
        className="shrink-0 opacity-70 hover:opacity-100"
      >
        <X size={14} />
      </button>
    </div>
  )
}
