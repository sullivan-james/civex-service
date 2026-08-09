import { useState, type FormEvent, type ReactNode } from 'react'
import { Modal, ModalBody, ModalFooter, ModalHeader } from './Modal'
import { Field } from './Field'
import { Input } from './Input'
import { NameLabelFields } from './NameLabelFields'
import { Button } from './Button'
import { nameError } from '../../utils/naming'
import { errorMessage } from '../../lib/errors'

export interface CreateResourceModalProps {
  /** Lowercase noun used in the header ("New {resourceLabel}") and submit
   * button ("Create {resourceLabel}"), e.g. "schema" or "collection". */
  resourceLabel: string
  nameLabel?: string
  namePlaceholder?: string
  /**
   * Resources whose `name` is a machine key referenced elsewhere (schemas,
   * fields) collect a display label first and derive the name from it. Pass
   * the capitalised noun to switch the modal into that mode; omit it for
   * resources whose name is just a name.
   */
  slugKind?: 'Schema' | 'Field'
  onClose: () => void
  onSubmit: (values: {
    name: string
    label: string
    description: string
  }) => Promise<unknown>
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
  slugKind,
  onClose,
  onSubmit,
  isPending,
  error,
  extraFields,
}: CreateResourceModalProps) {
  const [name, setName] = useState('')
  const [label, setLabel] = useState('')
  const [description, setDescription] = useState('')

  const invalidName = slugKind ? nameError(name.trim()) : null

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (invalidName) return
    await onSubmit({ name: name.trim(), label: label.trim(), description })
    onClose()
  }

  return (
    <Modal onClose={onClose}>
      <ModalHeader>New {resourceLabel}</ModalHeader>
      <form onSubmit={handleSubmit}>
        <ModalBody className="flex flex-col gap-3">
          {slugKind ? (
            <NameLabelFields
              kind={slugKind}
              value={{ label, name }}
              onChange={(next) => {
                setLabel(next.label)
                setName(next.name)
              }}
              autoFocus
            />
          ) : (
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
          )}
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
            <p role="alert" className="text-xs text-danger">
              {errorMessage(error)}
            </p>
          )}
        </ModalBody>
        <ModalFooter>
          <Button type="button" variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={
              isPending || !!invalidName || (!!slugKind && !name.trim())
            }
          >
            {isPending ? 'Creating…' : `Create ${resourceLabel}`}
          </Button>
        </ModalFooter>
      </form>
    </Modal>
  )
}
