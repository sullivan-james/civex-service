import type { ReactNode } from 'react'
import type { Collection } from '../../api/collections'
import type { Schema } from '../../api/schemas'
import { displayLabel } from '../../utils/naming'
import { Button, StepBadge } from '../ui'

/** The address of the Schemas page, opening on a new schema, with the schema
 * it goes inside when New schema… was pressed in a record. */
export function newSchemaHref(parentSchemaName?: string | null): string {
  const params = new URLSearchParams({ new: '1' })
  if (parentSchemaName) params.set('parent', parentSchemaName)
  return `/schemas?${params}`
}

/** What an empty list of records says: the two steps, which of them is
 * done, and a button for each. Making a schema is its own step, apart from
 * adding records, because they are different acts and were being mixed up. */
export function EmptyCollectionGuide({
  collection,
  schemas,
  within,
  newMenu,
  cannotAddSchema,
}: {
  /** None when the list is every collection at once. */
  collection: Collection | null | undefined
  schemas: Schema[]
  /** The record New was pressed in, and its schema, if any. */
  within?: { id: string; schema: Schema } | null
  /** The New menu for records, when there is a schema to add one of. */
  newMenu: ReactNode
  /** Why this person may not make a schema, when they may not. */
  cannotAddSchema?: string
}) {
  if (!collection)
    return (
      <div className="rounded-md border border-dashed border-border px-6 py-10 text-center">
        <p className="text-sm font-medium text-fg">No records yet</p>
        <p className="mt-1 text-sm text-fg-muted">
          Records live in collections. Make a collection first.
        </p>
        <Button variant="primary" size="sm" className="mt-4" to="/collections">
          Collections
        </Button>
      </div>
    )

  const label = (s: Schema) => displayLabel(s.name, s.label)
  const live = schemas.filter((s) => !s.deleted_at)
  // At the top: every top-level schema (a collection holds records of every
  // schema). Inside a record: the schemas that go inside its kind.
  const here = live.filter((s) =>
    within ? s.parent_id === within.schema.id : !s.parent_id,
  )
  const kind = within ? ` inside ${label(within.schema).toLowerCase()}s` : ''

  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-md border border-dashed border-border px-6 py-8"
    >
      <p className="text-sm font-medium text-fg">
        {within
          ? `Nothing in this ${label(within.schema).toLowerCase()} yet`
          : 'Nothing here yet'}
      </p>
      <ol className="mt-4 grid gap-4 sm:grid-cols-2">
        <li className="flex gap-3">
          <StepBadge index={1} state={here.length ? 'done' : 'current'} />
          <div className="min-w-0 space-y-2">
            <p className="text-sm text-fg">
              <span className="font-medium">A schema</span> is a kind of record
              and the fields it has.
            </p>
            <p className="text-sm text-fg-muted">
              {here.length
                ? `${kind ? `Inside ${label(within!.schema).toLowerCase()}s you have` : 'You have'} ${here.map(label).join(', ')}.`
                : `No schema${kind} yet. Set one up on the Schemas page, then come back.`}
            </p>
            {cannotAddSchema ? (
              <Button size="sm" disabled title={cannotAddSchema}>
                New schema…
              </Button>
            ) : (
              <Button
                size="sm"
                variant={here.length ? 'default' : 'primary'}
                to={newSchemaHref(within?.schema.name)}
              >
                New schema…
              </Button>
            )}
          </div>
        </li>
        <li className="flex gap-3">
          <StepBadge index={2} state={here.length ? 'current' : 'upcoming'} />
          <div className="min-w-0 space-y-2">
            <p className="text-sm text-fg">
              <span className="font-medium">A record</span> is one{' '}
              {here.length === 1 ? label(here[0]!).toLowerCase() : 'of them'}.
            </p>
            <p className="text-sm text-fg-muted">
              {here.length
                ? 'Add them one at a time, or bring in a spreadsheet from the New menu.'
                : 'Once there is a schema, add records of it here.'}
            </p>
            {here.length > 0 && newMenu}
          </div>
        </li>
      </ol>
    </div>
  )
}
