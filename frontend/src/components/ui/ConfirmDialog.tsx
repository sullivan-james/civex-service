import { useState, type ReactNode } from 'react'
import { Modal, ModalHeader, ModalBody, ModalFooter } from './Modal'
import { Button } from './Button'
import { Input } from './Input'

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
  /** Disable confirm for a reason other than isPending -- e.g. impact data
   * that's still loading and would otherwise let the button fire early. */
  confirmDisabled?: boolean
  /** Require the user to type this value verbatim before confirm is
   * enabled -- gates high-impact destructive actions behind an explicit,
   * hard-to-fat-finger acknowledgement instead of a single click. */
  typedConfirmationValue?: string
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
  confirmDisabled = false,
  typedConfirmationValue,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  const [typed, setTyped] = useState('')
  const typedMismatch =
    typedConfirmationValue != null && typed !== typedConfirmationValue
  const disabled = isPending || confirmDisabled || typedMismatch

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
        {typedConfirmationValue != null && (
          <div>
            <label
              htmlFor="confirm-dialog-typed-value"
              className="block text-xs text-fg-muted mb-1"
            >
              Type{' '}
              <span className="font-mono font-medium text-fg">
                {typedConfirmationValue}
              </span>{' '}
              to confirm
            </label>
            <Input
              id="confirm-dialog-typed-value"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              disabled={isPending}
              autoComplete="off"
              autoFocus
            />
          </div>
        )}
      </ModalBody>
      <ModalFooter>
        <Button
          variant="default"
          onClick={onClose}
          disabled={isPending}
          autoFocus={variant === 'danger' && typedConfirmationValue == null}
        >
          Cancel
        </Button>
        <Button
          variant={variant === 'danger' ? 'danger' : 'primary'}
          onClick={onConfirm}
          disabled={disabled}
          autoFocus={variant !== 'danger'}
        >
          {isPending ? 'Working…' : confirmLabel}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
