import { Link } from 'react-router-dom'
import { useDatasets } from '../hooks/useDatasets'
import { Badge, EmptyState, ErrorState, LoadingState, MonoId, PageHeader, Table, Tbody, Td, Th, Thead, Tr } from '../components/ui'
import { pluralise } from '../lib/utils'

export default function DatasetsPage() {
  const { data, isLoading, error } = useDatasets()

  return (
    <>
      <PageHeader title="Datasets" />

      {isLoading && <LoadingState />}
      {error && <ErrorState message={String(error)} />}

      {data?.length === 0 && (
        <EmptyState
          title="No datasets yet"
          message="Create one with `civex dataset create`."
        />
      )}

      {data && data.length > 0 && (
        <Table>
          <Thead>
            <tr>
              <Th>Name</Th>
              <Th>Records</Th>
              <Th>Description</Th>
              <Th className="w-28">ID</Th>
            </tr>
          </Thead>
          <Tbody>
            {data.map(d => (
              <Tr key={d.id}>
                <Td>
                  <Link to={`/datasets/${d.id}`} className="font-medium text-[#0969da] hover:underline">
                    {d.name}
                  </Link>
                </Td>
                <Td>
                  <Badge variant={d.record_count > 0 ? 'success' : 'default'}>
                    {pluralise(d.record_count, 'record')}
                  </Badge>
                </Td>
                <Td className="text-[#656d76]">{d.description ?? ''}</Td>
                <Td><MonoId id={d.id} /></Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </>
  )
}
