import { Link } from 'react-router-dom'
import { useSchemas } from '../hooks/useSchemas'
import { Badge, EmptyState, ErrorState, LoadingState, MonoId, PageHeader, Table, Tbody, Td, Th, Thead, Tr } from '../components/ui'
import { pluralise } from '../lib/utils'

export default function SchemasPage() {
  const { data, isLoading, error } = useSchemas()

  const nameById = Object.fromEntries((data ?? []).map(s => [s.id, s.name]))

  return (
    <>
      <PageHeader title="Schemas" />

      {isLoading && <LoadingState />}
      {error && <ErrorState message={String(error)} />}

      {data?.length === 0 && (
        <EmptyState
          title="No schemas yet"
          message="Create one with `civex schema create`."
        />
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
