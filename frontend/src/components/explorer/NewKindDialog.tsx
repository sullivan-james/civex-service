import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import type { Collection } from '../../api/collections'
import type { Schema } from '../../api/schemas'
import { useUpdateCollection } from '../../hooks/useCollections'
import { useCreateSchema } from '../../hooks/useSchemas'
import { errorMessage } from '../../lib/errors'
import { displayLabel, slugify } from '../../utils/naming'
import {
  Button,
  Field,
  Input,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
} from '../ui'

/** "New ▸ Something else…": a kind of record this collection doesn't have
 * yet. One box. Pressed inside a record, the new kind goes inside that
 * record's kind, so where New was pressed is the hierarchy. The kind is
 * listed on the collection and a blank record of it opens; its fields are
 * added on that form. A kind that exists already is offered instead. */
export function NewKindDialog({
  collection,
  schemas,
  within,
  onClose,
}: {
  collection: Collection
  schemas: Schema[]
  /** The record New was pressed in, and its kind, if any. */
  within?: { id: string; schema: Schema } | null
  onClose: () => void
}) {
  const navigate = useNavigate()
  const createSchema = useCreateSchema()
  const updateCollection = useUpdateCollection()
  const [label, setLabel] = useState('')
  const name = slugify(label.trim())
  const existing = name
    ? schemas.find((s) => s.name === name && !s.deleted_at)
    : undefined
  // An existing kind is reused only where it fits: at the top, or inside a
  // record of the kind it goes inside.
  const fits =
    existing &&
    (within ? existing.parent_id === within.schema.id : !existing.parent_id)
  const pending = createSchema.isPending || updateCollection.isPending
  const error = createSchema.error ?? updateCollection.error

  function open(schemaName: string) {
    onClose()
    navigate(
      `/collections/${collection.id}/new?${new URLSearchParams({
        schema: schemaName,
        ...(within ? { parent: within.id } : {}),
      })}`,
    )
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!name || pending) return
    if (existing && !fits) return
    let schemaName = existing?.name
    if (!schemaName) {
      const created = await createSchema.mutateAsync({
        name,
        label: label.trim(),
        parent: within?.schema.name,
      })
      schemaName = created.name
    }
    if (!collection.schemas.includes(schemaName))
      await updateCollection.mutateAsync({
        name: collection.name,
        body: { schemas: [...collection.schemas, schemaName] },
      })
    open(schemaName)
  }

  const where = within
    ? `inside ${displayLabel(within.schema.name, within.schema.label).toLowerCase()}s`
    : null
  return (
    <Modal onClose={onClose} size="sm" dismissible={!pending}>
      <ModalHeader>{where ? `New, ${where}` : 'New'}</ModalHeader>
      <form onSubmit={submit}>
        <ModalBody>
          <Field label="What are you adding?" required>
            <Input
              autoFocus
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Visit"
              className="w-full"
            />
          </Field>
          {existing && (
            <p className="mt-2 text-sm text-fg-muted" role="status">
              {fits
                ? `You already have ${displayLabel(existing.name, existing.label).toLowerCase()}s.`
                : `${displayLabel(existing.name, existing.label)} already exists and goes somewhere else.`}
            </p>
          )}
          {error && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {errorMessage(error)}
            </p>
          )}
        </ModalBody>
        <ModalFooter>
          <Button type="button" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={!name || pending || (!!existing && !fits)}
          >
            {pending
              ? 'Starting…'
              : `New ${(existing && fits ? displayLabel(existing.name, existing.label) : label.trim() || '…').toLowerCase()}`}
          </Button>
        </ModalFooter>
      </form>
    </Modal>
  )
}
