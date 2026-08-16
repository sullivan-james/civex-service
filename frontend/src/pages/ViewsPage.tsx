import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router'
import { useSchema } from '../hooks/useSchemas'
import { useViews, useDeleteView } from '../hooks/useViews'
import {
  Page,
  Button,
  Table,
  Thead,
  Th,
  Tbody,
  Tr,
  Td,
  IconButton,
  ConfirmDialog,
  TableSkeleton,
  ErrorState,
  EmptyState,
} from '../components/ui'
import { X } from '../components/ui/icons'
import { displayLabel } from '../utils/naming'
import { errorMessage } from '../lib/errors'
import { pluralise } from '../lib/utils'

export default function ViewsPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const {
    data: schema,
    isLoading: schemaLoading,
    error: schemaError,
  } = useSchema(id!)
  const schemaName = schema?.name ?? ''
  const { data: views, isLoading, error } = useViews(schemaName)
  const deleteView = useDeleteView(schemaName)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const breadcrumbs = [
    { label: 'Schemas', to: '/schemas' },
    ...(schema
      ? [
          {
            label: displayLabel(schema.name, schema.label),
            to: `/schemas/${id}`,
          },
        ]
      : []),
  ]

  if (schemaLoading) {
    return (
      <Page breadcrumbs={breadcrumbs} loading={<TableSkeleton rows={4} />} />
    )
  }
  if (schemaError || !schema) {
    return (
      <Page
        breadcrumbs={breadcrumbs}
        error={
          <ErrorState
            message={
              schemaError ? errorMessage(schemaError) : 'Schema not found'
            }
          />
        }
      />
    )
  }

  return (
    <Page
      breadcrumbs={[...breadcrumbs, { label: 'Views' }]}
      title={`Views · ${displayLabel(schema.name, schema.label)}`}
      description="Saved column/filter selections for browsing this schema's records."
      action={
        <Button
          variant="primary"
          size="sm"
          onClick={() => navigate(`/schemas/${id}/views/new`)}
        >
          + New view
        </Button>
      }
    >
      {isLoading && (
        <TableSkeleton columns={['w-48', 'w-32', 'w-16']} rows={4} />
      )}
      {error && <ErrorState message={errorMessage(error)} />}

      {views && views.length === 0 && (
        <EmptyState
          title="No views yet"
          message="Build a column/filter selection and save it as a view to browse this schema's records with joins resolved."
        />
      )}

      {views && views.length > 0 && (
        <Table>
          <Thead>
            <tr>
              <Th>Name</Th>
              <Th>Columns</Th>
              <Th className="w-16" />
            </tr>
          </Thead>
          <Tbody>
            {views.map((view) => (
              <Tr key={view.id}>
                <Td>
                  <Link
                    to={`/schemas/${id}/views/${view.name}`}
                    className="font-medium text-accent hover:underline"
                  >
                    {view.name}
                  </Link>
                </Td>
                <Td className="text-fg-muted">
                  {view.columns.length === 0
                    ? 'No columns'
                    : pluralise(view.columns.length, 'column')}
                </Td>
                <Td>
                  <IconButton
                    icon={X}
                    aria-label={`Delete view ${view.name}`}
                    variant="danger"
                    onClick={() => setConfirmDelete(view.name)}
                  />
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}

      {confirmDelete && (
        <ConfirmDialog
          title="Delete view"
          body={`Delete view '${confirmDelete}'? This cannot be undone.`}
          confirmLabel="Delete"
          variant="danger"
          isPending={deleteView.isPending}
          warning={
            deleteView.error ? errorMessage(deleteView.error) : undefined
          }
          onConfirm={() =>
            deleteView.mutate(confirmDelete, {
              onSuccess: () => setConfirmDelete(null),
            })
          }
          onClose={() => setConfirmDelete(null)}
        />
      )}
    </Page>
  )
}
