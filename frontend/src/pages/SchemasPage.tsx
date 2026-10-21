import { useState } from 'react'
import { useSchemas, useCreateSchema } from '../hooks/useSchemas'
import {
  Badge,
  Button,
  CreateResourceModal,
  Field,
  MonoId,
  Page,
  Select,
  DataTable,
} from '../components/ui'
import { displayLabel } from '../utils/naming'
import { pluralise } from '../lib/utils'
import { errorMessage } from '../lib/errors'

function CreateSchemaModal({ onClose }: { onClose: () => void }) {
  const [parent, setParent] = useState('')
  const create = useCreateSchema()
  const { data: schemas } = useSchemas()

  return (
    <CreateResourceModal
      resourceLabel="schema"
      slugKind="Schema"
      onClose={onClose}
      isPending={create.isPending}
      error={create.error}
      onSubmit={async ({ name, label, description }) => {
        await create.mutateAsync({
          name,
          label: label || undefined,
          description: description || undefined,
          parent: parent || undefined,
        })
      }}
      extraFields={
        <Field
          label="Goes inside (optional)"
          info="Records of this type sit inside a record of the type you pick here (a Sample inside a Visit), and can use its fields."
        >
          <Select
            value={parent}
            onChange={(e) => setParent(e.target.value)}
            className="w-full"
          >
            <option value="">None</option>
            {schemas?.map((s) => (
              <option key={s.id} value={s.name}>
                {displayLabel(s.name, s.label)}
              </option>
            ))}
          </Select>
        </Field>
      }
    />
  )
}

export default function SchemasPage() {
  const { data, isLoading, error } = useSchemas()
  const [showCreate, setShowCreate] = useState(false)

  const labelById = Object.fromEntries(
    (data ?? []).map((s) => [s.id, displayLabel(s.name, s.label)]),
  )

  return (
    <Page
      title="Schemas"
      info="A schema is a blank form: the fields a kind of thing has. You design it once, then add a record every time you have another one."
      action={
        <Button variant="primary" onClick={() => setShowCreate(true)}>
          New schema
        </Button>
      }
    >
      {showCreate && <CreateSchemaModal onClose={() => setShowCreate(false)} />}

      <DataTable
        layout="auto"
        columns={[
          {
            key: 'name',
            header: 'Name',
            render: (s) => (
              <>
                <span className="font-medium">
                  {displayLabel(s.name, s.label)}
                </span>
                <span className="block font-mono text-xs text-fg-subtle">
                  {s.name}
                </span>
              </>
            ),
          },
          {
            key: 'parent',
            header: 'Goes inside',
            render: (s) =>
              s.parent_id ? (
                <Badge variant="accent">{labelById[s.parent_id] ?? '—'}</Badge>
              ) : (
                <span className="text-fg-subtle">—</span>
              ),
          },
          {
            key: 'fields',
            header: 'Fields',
            render: (s) => <Badge>{pluralise(s.fields.length, 'field')}</Badge>,
          },
          {
            key: 'description',
            header: 'Description',
            className: 'text-fg-muted',
            render: (s) => s.description ?? '',
          },
          {
            key: 'id',
            header: 'ID',
            width: '7rem',
            render: (s) => <MonoId id={s.id} />,
          },
        ]}
        rows={data ?? []}
        getRowId={(s) => s.id}
        rowHref={(s) => `/schemas/${s.id}`}
        isLoading={isLoading}
        error={error ? errorMessage(error) : undefined}
        emptyTitle="No schemas yet"
        emptyMessage="Make one here, or with New ▸ New schema… in a collection."
        emptyAction={
          <Button variant="primary" onClick={() => setShowCreate(true)}>
            New schema
          </Button>
        }
      />
    </Page>
  )
}
