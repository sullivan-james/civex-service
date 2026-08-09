import type { ReactNode } from 'react'
import { Modal, ModalHeader, ModalBody, ModalFooter } from './Modal'
import { Button } from './Button'

interface ConfirmDialogProps {
  title: string
  body: ReactNode
  confirmLabel?: string
  variant?: 'danger' | 'default'
  /** Extra alert rendered inside the same dialog -- e.g. a backend warning
   * from a first attempt, or the error from a failed retry. Presenting it
   * here (instead of a second stacked confirm) keeps the escalation to one
   * dialog. */
  warning?: ReactNode
  isPending?: boolean
  onConfirm: () => void
  onClose: () => void
}

export function ConfirmDialog({
  title,
  body,
  confirmLabel = 'Confirm',
  variant = 'default',
  warning,
  isPending = false,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  return (
    <Modal onClose={onClose} size="sm" dismissible={!isPending}>
      <ModalHeader onClose={isPending ? undefined : onClose}>
        {title}
      </ModalHeader>
      <ModalBody className="space-y-3">
        <div className="text-sm text-fg">{body}</div>
        {warning && (
          <div className="text-xs bg-danger-subtle border border-danger-subtle-border rounded-md p-2 text-danger">
            {warning}
          </div>
        )}
      </ModalBody>
      <ModalFooter>
        <Button
          variant="default"
          onClick={onClose}
          disabled={isPending}
          autoFocus={variant === 'danger'}
        >
          Cancel
        </Button>
        <Button
          variant={variant === 'danger' ? 'danger' : 'primary'}
          onClick={onConfirm}
          disabled={isPending}
          autoFocus={variant !== 'danger'}
        >
          {isPending ? 'Working…' : confirmLabel}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
