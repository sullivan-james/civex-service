import { useState } from 'react'
import { Link } from 'react-router'
import { useAllViews, useDeleteView } from '../hooks/useViews'
import { useSchemas } from '../hooks/useSchemas'
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
import type { View } from '../api/views'
import type { Schema } from '../api/schemas'

function SchemaViewGroup({ schema, views }: { schema: Schema; views: View[] }) {
  const deleteView = useDeleteView(schema.name)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  return (
    <div className="border border-border rounded-md overflow-hidden">
      <div className="flex items-center justify-between gap-4 px-4 py-3 bg-canvas-subtle border-b border-border">
        <Link
          to={`/schemas/${schema.id}`}
          className="text-sm font-semibold text-fg hover:underline"
        >
          {displayLabel(schema.name, schema.label)}
        </Link>
        <Link to={`/schemas/${schema.id}/views/new`}>
          <Button size="sm" variant="primary">
            + New view
          </Button>
        </Link>
      </div>
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
                  to={`/schemas/${schema.id}/views/${view.name}`}
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
    </div>
  )
}

export default function ViewsIndexPage() {
  const {
    data: views,
    isLoading: viewsLoading,
    error: viewsError,
  } = useAllViews()
  const {
    data: schemas,
    isLoading: schemasLoading,
    error: schemasError,
  } = useSchemas()

  const isLoading = viewsLoading || schemasLoading
  const error = viewsError ?? schemasError

  const groups: { schema: Schema; views: View[] }[] = []
  if (views && schemas) {
    const bySchemaId = new Map<string, View[]>()
    for (const view of views) {
      const list = bySchemaId.get(view.schema_id) ?? []
      list.push(view)
      bySchemaId.set(view.schema_id, list)
    }
    for (const schema of schemas) {
      const schemaViews = bySchemaId.get(schema.id)
      if (schemaViews && schemaViews.length > 0) {
        groups.push({ schema, views: schemaViews })
      }
    }
  }

  return (
    <Page
      title="Views"
      description="Saved column/filter selections for browsing and exporting records, grouped by schema."
    >
      {isLoading && (
        <TableSkeleton columns={['w-48', 'w-32', 'w-16']} rows={4} />
      )}
      {error && <ErrorState message={errorMessage(error)} />}

      {views && views.length === 0 && (
        <EmptyState
          title="No views yet"
          message="Open a schema and build a column/filter selection to save it as a view."
        />
      )}

      {groups.length > 0 && (
        <div className="flex flex-col gap-6">
          {groups.map(({ schema, views: schemaViews }) => (
            <SchemaViewGroup
              key={schema.id}
              schema={schema}
              views={schemaViews}
            />
          ))}
        </div>
      )}
    </Page>
  )
}
