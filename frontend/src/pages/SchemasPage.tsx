import { useState } from 'react'
import { Link } from 'react-router'
import { useSchemas, useCreateSchema } from '../hooks/useSchemas'
import {
  Badge,
  Button,
  CreateResourceModal,
  ErrorState,
  Field,
  TableSkeleton,
  MonoId,
  PageHeader,
  Select,
  Table,
  Tbody,
  Td,
  Th,
  Thead,
  Tr,
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
        <Field label="Parent schema">
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
    <>
      {showCreate && <CreateSchemaModal onClose={() => setShowCreate(false)} />}

      <PageHeader
        title="Schemas"
        action={
          <Button variant="primary" onClick={() => setShowCreate(true)}>
            New schema
          </Button>
        }
      />

      {isLoading && (
        <TableSkeleton
          columns={['w-32', 'w-20', 'w-16', 'w-48', 'w-20']}
          rows={8}
        />
      )}
      {error && <ErrorState message={errorMessage(error)} />}

      {data?.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <svg
            width="40"
            height="40"
            viewBox="0 0 16 16"
            fill="none"
            className="mb-4 text-border"
            aria-hidden
          >
            <rect
              x="2"
              y="1"
              width="12"
              height="14"
              rx="2"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <path
              d="M5 5h6M5 8h6M5 11h4"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
          <h2 className="text-lg font-semibold text-fg mb-2">No schemas yet</h2>
          <p className="text-sm text-fg-muted mb-6 max-w-sm">
            Schemas define the structure of your data — field names, types, and
            rules. Create a schema before adding records.
          </p>
          <Button variant="primary" onClick={() => setShowCreate(true)}>
            Create schema
          </Button>
        </div>
      )}

      {data && data.length > 0 && (
        <Table>
          <Thead>
            <tr>
              <Th>Name</Th>
              <Th>Parent</Th>
              <Th>Fields</Th>
              <Th>Description</Th>
              <Th className="w-28">ID</Th>
            </tr>
          </Thead>
          <Tbody>
            {data.map((s) => (
              <Tr key={s.id}>
                <Td>
                  <Link
                    to={`/schemas/${s.id}`}
                    className="font-medium text-accent hover:underline"
                  >
                    {displayLabel(s.name, s.label)}
                  </Link>
                  <div
                    className="font-mono text-xs text-fg-subtle"
                    title="Schema name — what workflows and CSV headers reference"
                  >
                    {s.name}
                  </div>
                </Td>
                <Td>
                  {s.parent_id ? (
                    <Link to={`/schemas/${s.parent_id}`}>
                      <Badge variant="accent">
                        {labelById[s.parent_id] ?? '—'}
                      </Badge>
                    </Link>
                  ) : (
                    <span className="text-fg-subtle">—</span>
                  )}
                </Td>
                <Td>
                  <Badge>{pluralise(s.fields.length, 'field')}</Badge>
                </Td>
                <Td className="text-fg-muted">{s.description ?? ''}</Td>
                <Td>
                  <MonoId id={s.id} />
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </>
  )
}
