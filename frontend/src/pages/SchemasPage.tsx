import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useSchemas, useCreateSchema } from '../hooks/useSchemas'
import { Badge, Button, ErrorState, LoadingState, MonoId, PageHeader, Table, Tbody, Td, Th, Thead, Tr } from '../components/ui'
import { pluralise } from '../lib/utils'

function CreateSchemaModal({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [parent, setParent] = useState('')
  const create = useCreateSchema()
  const { data: schemas } = useSchemas()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    await create.mutateAsync({ name, description: description || undefined, parent: parent || undefined })
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-lg border border-[#d0d7de] shadow-lg w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
        <h2 className="text-base font-semibold text-[#1f2328] mb-4">New schema</h2>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div>
            <label className="block text-xs font-medium text-[#1f2328] mb-1">Name <span className="text-[#d1242f]">*</span></label>
            <input
              autoFocus
              required
              value={name}
              onChange={e => setName(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-[#d0d7de] rounded-md focus:outline-none focus:ring-2 focus:ring-[#0969da] focus:border-[#0969da]"
              placeholder="my-schema"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#1f2328] mb-1">Description</label>
            <input
              value={description}
              onChange={e => setDescription(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-[#d0d7de] rounded-md focus:outline-none focus:ring-2 focus:ring-[#0969da] focus:border-[#0969da]"
              placeholder="Optional"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#1f2328] mb-1">Parent schema</label>
            <select
              value={parent}
              onChange={e => setParent(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-[#d0d7de] rounded-md focus:outline-none focus:ring-2 focus:ring-[#0969da] focus:border-[#0969da] bg-white"
            >
              <option value="">None</option>
              {schemas?.map(s => (
                <option key={s.id} value={s.name}>{s.name}</option>
              ))}
            </select>
          </div>
          {create.error && (
            <p className="text-xs text-[#d1242f]">{String(create.error)}</p>
          )}
          <div className="flex justify-end gap-2 mt-1">
            <Button type="button" variant="default" onClick={onClose}>Cancel</Button>
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

  const nameById = Object.fromEntries((data ?? []).map(s => [s.id, s.name]))

  return (
    <>
      {showCreate && <CreateSchemaModal onClose={() => setShowCreate(false)} />}

      <PageHeader
        title="Schemas"
        action={<Button variant="primary" onClick={() => setShowCreate(true)}>New schema</Button>}
      />

      {isLoading && <LoadingState />}
      {error && <ErrorState message={String(error)} />}

      {data?.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <svg width="40" height="40" viewBox="0 0 16 16" fill="none" className="mb-4 text-[#d0d7de]" aria-hidden>
            <rect x="2" y="1" width="12" height="14" rx="2" stroke="currentColor" strokeWidth="1.5"/>
            <path d="M5 5h6M5 8h6M5 11h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <h2 className="text-lg font-semibold text-[#1f2328] mb-2">No schemas yet</h2>
          <p className="text-sm text-[#656d76] mb-6 max-w-sm">
            Schemas define the structure of your data — field names, types, and rules. Create a schema before adding records.
          </p>
          <Button variant="primary" onClick={() => setShowCreate(true)}>Create schema</Button>
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
            {data.map(s => (
              <Tr key={s.id}>
                <Td>
                  <Link to={`/schemas/${s.id}`} className="font-medium text-[#0969da] hover:underline">
                    {s.name}
                  </Link>
                </Td>
                <Td>
                  {s.parent_id
                    ? (
                      <Link to={`/schemas/${s.parent_id}`}>
                        <Badge variant="accent">{nameById[s.parent_id] ?? '—'}</Badge>
                      </Link>
                    )
                    : <span className="text-[#818b98]">—</span>
                  }
                </Td>
                <Td><Badge>{pluralise(s.fields.length, 'field')}</Badge></Td>
                <Td className="text-[#656d76]">{s.description ?? ''}</Td>
                <Td><MonoId id={s.id} /></Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </>
  )
}
