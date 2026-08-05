import { useState } from 'react'
import { Link } from 'react-router'
import { useSchemas, useCreateSchema } from '../hooks/useSchemas'
import {
  Badge,
  Button,
  ErrorState,
  Input,
  LoadingState,
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
import { pluralise } from '../lib/utils'
import { errorMessage } from '../lib/errors'

function CreateSchemaModal({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [parent, setParent] = useState('')
  const create = useCreateSchema()
  const { data: schemas } = useSchemas()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    await create.mutateAsync({
      name,
      description: description || undefined,
      parent: parent || undefined,
    })
    onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg border border-border shadow-lg w-full max-w-md p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold text-fg mb-4">New schema</h2>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div>
            <label className="block text-xs font-medium text-fg mb-1">
              Name <span className="text-danger">*</span>
            </label>
            <Input
              autoFocus
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full"
              placeholder="my-schema"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-fg mb-1">
              Description
            </label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full"
              placeholder="Optional"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-fg mb-1">
              Parent schema
            </label>
            <Select
              value={parent}
              onChange={(e) => setParent(e.target.value)}
              className="w-full"
            >
              <option value="">None</option>
              {schemas?.map((s) => (
                <option key={s.id} value={s.name}>
                  {s.name}
                </option>
              ))}
            </Select>
          </div>
          {create.error && (
            <p className="text-xs text-danger">{errorMessage(create.error)}</p>
          )}
          <div className="flex justify-end gap-2 mt-1">
            <Button type="button" variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={create.isPending}>
              {create.isPending ? 'Creating…' : 'Create schema'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function SchemasPage() {
  const { data, isLoading, error } = useSchemas()
  const [showCreate, setShowCreate] = useState(false)

  const nameById = Object.fromEntries((data ?? []).map((s) => [s.id, s.name]))

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

      {isLoading && <LoadingState />}
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
                    {s.name}
                  </Link>
                </Td>
                <Td>
                  {s.parent_id ? (
                    <Link to={`/schemas/${s.parent_id}`}>
                      <Badge variant="accent">
                        {nameById[s.parent_id] ?? '—'}
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
