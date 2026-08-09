import { useState, type FormEvent, type ReactNode } from 'react'
import { Modal, ModalBody, ModalFooter, ModalHeader } from './Modal'
import { Field } from './Field'
import { Input } from './Input'
import { Button } from './Button'
import { errorMessage } from '../../lib/errors'

export interface CreateResourceModalProps {
  /** Lowercase noun used in the header ("New {resourceLabel}") and submit
   * button ("Create {resourceLabel}"), e.g. "schema" or "collection". */
  resourceLabel: string
  nameLabel?: string
  namePlaceholder?: string
  onClose: () => void
  onSubmit: (values: { name: string; description: string }) => Promise<unknown>
  isPending: boolean
  error: unknown
  /** Resource-specific inputs (e.g. a parent-schema selector) rendered after
   * the description field. The caller owns their own state and reads it via
   * closure in onSubmit. */
  extraFields?: ReactNode
}

export function CreateResourceModal({
  resourceLabel,
  nameLabel = 'Name',
  namePlaceholder,
  onClose,
  onSubmit,
  isPending,
  error,
  extraFields,
}: CreateResourceModalProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    await onSubmit({ name, description })
    onClose()
  }

  return (
    <Modal onClose={onClose}>
      <ModalHeader>New {resourceLabel}</ModalHeader>
      <form onSubmit={handleSubmit}>
        <ModalBody className="flex flex-col gap-3">
          <Field label={nameLabel} required>
            <Input
              autoFocus
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full"
              placeholder={namePlaceholder}
            />
          </Field>
          <Field label="Description">
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full"
              placeholder="Optional"
            />
          </Field>
          {extraFields}
          {error != null && (
            <p className="text-xs text-danger">{errorMessage(error)}</p>
          )}
        </ModalBody>
        <ModalFooter>
          <Button type="button" variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={isPending}>
            {isPending ? 'Creating…' : `Create ${resourceLabel}`}
          </Button>
        </ModalFooter>
      </form>
    </Modal>
  )
}
