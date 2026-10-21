import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import type { Collection } from '../../api/collections'
import { useUpdateCollection } from '../../hooks/useCollections'
import { useCreateSchema } from '../../hooks/useSchemas'
import { errorMessage } from '../../lib/errors'
import { nameError } from '../../utils/naming'
import {
  Button,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  NameLabelFields,
} from '../ui'

/** A collection with no record types yet starts from its first record: the
 * person says what they record here ("Sample"), which makes the record type,
 * lists it on the collection, and opens a blank record of it where the
 * fields are added one by one. Nobody has to visit Record types first. */
export function StartWithRecordDialog({
  collection,
  onClose,
}: {
  collection: Collection
  onClose: () => void
}) {
  const navigate = useNavigate()
  const createSchema = useCreateSchema()
  const updateCollection = useUpdateCollection()
  const [value, setValue] = useState({ label: '', name: '' })
  const invalid = value.name ? nameError(value.name) : 'Say what you record.'
  const pending = createSchema.isPending || updateCollection.isPending
  const error = createSchema.error ?? updateCollection.error

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (invalid) return
    const created = await createSchema.mutateAsync({
      name: value.name,
      label: value.label || undefined,
    })
    await updateCollection.mutateAsync({
      name: collection.name,
      body: { schemas: [...collection.schemas, created.name] },
    })
    onClose()
    navigate(
      `/collections/${collection.id}/new?${new URLSearchParams({ schema: created.name })}`,
    )
  }

  return (
    <Modal onClose={onClose} dismissible={!pending}>
      <ModalHeader>Start with a record</ModalHeader>
      <form onSubmit={submit}>
        <ModalBody className="space-y-3">
          <p className="text-sm text-fg-muted">
            What do you record in {collection.name}? One kind of thing, in the
            singular: a sample, a site, an interview. That becomes the record
            type, a blank form, and you fill in its first copy next, adding the
            fields as you go.
          </p>
          <NameLabelFields
            kind="Schema"
            value={value}
            onChange={setValue}
            autoFocus
          />
          {error && (
            <p role="alert" className="text-sm text-danger">
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
            disabled={!!invalid || pending}
          >
            {pending ? 'Starting…' : 'Add the first record'}
          </Button>
        </ModalFooter>
      </form>
    </Modal>
  )
}
