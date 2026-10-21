import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import type { Collection } from '../../api/collections'
import type { Schema } from '../../api/schemas'
import { useUpdateCollection } from '../../hooks/useCollections'
import { useCreateSchema } from '../../hooks/useSchemas'
import { errorMessage } from '../../lib/errors'
import { displayLabel, nameError } from '../../utils/naming'
import {
  Button,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  NameLabelFields,
} from '../ui'

/** "New ▸ New schema…" from a list of records: says what a schema is, shows
 * the ones there are, and makes one where the person is. Pressed inside a
 * record, the new schema goes inside that record's, so where New was
 * pressed is the hierarchy. The schema is listed on the collection and a
 * blank record of it opens, where its fields are added. The Schemas page is
 * one click away for anyone who would rather set it up there. */
export function NewSchemaDialog({
  collection,
  schemas,
  within,
  onClose,
}: {
  collection: Collection
  schemas: Schema[]
  /** The record New was pressed in, and its schema, if any. */
  within?: { id: string; schema: Schema } | null
  onClose: () => void
}) {
  const navigate = useNavigate()
  const createSchema = useCreateSchema()
  const updateCollection = useUpdateCollection()
  const [value, setValue] = useState({ label: '', name: '' })
  const name = value.name.trim()
  const invalid = name ? nameError(name) : 'required'
  const live = schemas.filter((s) => !s.deleted_at)
  const existing = name ? live.find((s) => s.name === name) : undefined
  // One that exists is reused only where it fits: at the top, or inside a
  // record of the schema it goes inside.
  const fits =
    existing &&
    (within ? existing.parent_id === within.schema.id : !existing.parent_id)
  // What is here already: at the top, the collection's top-level schemas;
  // inside a record, the schemas that go inside its kind.
  const here = live.filter((s) =>
    within
      ? s.parent_id === within.schema.id
      : !s.parent_id && collection.schemas.includes(s.name),
  )
  const pending = createSchema.isPending || updateCollection.isPending
  const error = createSchema.error ?? updateCollection.error
  const label = (s: Schema) => displayLabel(s.name, s.label)

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
    if (invalid || pending || (existing && !fits)) return
    let schemaName = existing?.name
    if (!schemaName) {
      const created = await createSchema.mutateAsync({
        name,
        label: value.label.trim() || undefined,
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

  return (
    <Modal onClose={onClose} dismissible={!pending}>
      <ModalHeader>New schema</ModalHeader>
      <form onSubmit={submit}>
        <ModalBody className="space-y-3">
          <p className="text-sm text-fg-muted">
            A schema is the form every record of one kind fills in: its fields
            and their rules. Make one for a new kind of thing, not for each new
            record.
          </p>
          <p className="text-sm text-fg-muted">
            {within ? (
              <>
                Inside {label(within.schema).toLowerCase()}s there{' '}
                {here.length === 1 ? 'is' : 'are'}{' '}
                {here.length ? here.map(label).join(', ') : 'no schemas yet'}.
                The new one goes inside{' '}
                <strong className="text-fg">{label(within.schema)}</strong> too.
              </>
            ) : (
              <>
                This collection has{' '}
                {here.length ? here.map(label).join(', ') : 'no schemas yet'}.
              </>
            )}
          </p>
          <NameLabelFields
            kind="Schema"
            value={value}
            onChange={setValue}
            autoFocus
          />
          {existing && (
            <p className="text-sm text-fg-muted">
              {fits
                ? `${label(existing)} exists already; a new record of it opens.`
                : `${label(existing)} exists already and goes somewhere else.`}
            </p>
          )}
          {error && (
            <p role="alert" className="text-sm text-danger">
              {errorMessage(error)}
            </p>
          )}
          <p className="text-sm">
            <Button
              variant="link"
              onClick={() => {
                onClose()
                navigate('/schemas')
              }}
            >
              Set it up on the Schemas page instead
            </Button>
          </p>
        </ModalBody>
        <ModalFooter>
          <Button type="button" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={!!invalid || pending || (!!existing && !fits)}
          >
            {pending
              ? 'Creating…'
              : existing && fits
                ? `New ${label(existing).toLowerCase()}`
                : 'Create and add the first record'}
          </Button>
        </ModalFooter>
      </form>
    </Modal>
  )
}
