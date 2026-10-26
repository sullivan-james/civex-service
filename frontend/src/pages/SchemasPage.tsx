import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
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

function CreateSchemaModal({
  onClose,
  initialParent = '',
}: {
  onClose: () => void
  /** The schema the new one goes inside, when New schema… was pressed in a record. */
  initialParent?: string
}) {
  const [parent, setParent] = useState(initialParent)
  const create = useCreateSchema()
  const { data: schemas } = useSchemas()
  const navigate = useNavigate()

  return (
    <CreateResourceModal
      resourceLabel="schema"
      slugKind="Schema"
      onClose={onClose}
      isPending={create.isPending}
      error={create.error}
      onSubmit={async ({ name, label, description }) => {
        const created = await create.mutateAsync({
          name,
          label: label || undefined,
          description: description || undefined,
          parent: parent || undefined,
        })
        // Next comes its fields: the schema's own page.
        navigate(`/schemas/${created.id}`)
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
  const [params, setParams] = useSearchParams()
  // `?new=1&parent=` is New schema… from a list of records:
  // the dialog opens with that context, and closing it clears the address.
  const fromList = params.get('new') === '1'
  const [showCreate, setShowCreate] = useState(false)
  const creating = showCreate || fromList
  const closeCreate = () => {
    setShowCreate(false)
    if (fromList) setParams({}, { replace: true })
  }

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
      {creating && (
        <CreateSchemaModal
          onClose={closeCreate}
          initialParent={params.get('parent') ?? ''}
        />
      )}

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
        emptyMessage="Make one here, or from a collection's page."
        emptyAction={
          <Button variant="primary" onClick={() => setShowCreate(true)}>
            New schema
          </Button>
        }
      />
    </Page>
  )
}
