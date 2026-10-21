import { useParams } from 'react-router'
import { useSchema } from '../hooks/useSchemas'
import { DetailSkeleton, ErrorState, Page } from '../components/ui'
import { RecordsExplorer } from '../components/explorer/RecordsExplorer'
import { displayLabel } from '../utils/naming'
import { errorMessage } from '../lib/errors'

/** A schema's records across every collection -- the same explorer a
 * collection uses, fixed to one schema and not scoped to a collection.
 * Saved views open here (`?view=name`), and new ones are made here with
 * "Save as view". */
export default function SchemaRecordsPage() {
  const { id } = useParams<{ id: string }>()
  const { data: schema, isLoading, error } = useSchema(id!)

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

  if (isLoading)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        loading={<DetailSkeleton sections={2} />}
      />
    )
  if (error || !schema)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        error={
          <ErrorState
            message={error ? errorMessage(error) : 'Schema not found'}
          />
        }
      />
    )

  return (
    <Page
      breadcrumbs={[...breadcrumbs, { label: 'Records' }]}
      title={`${displayLabel(schema.name, schema.label)} records`}
      info="Across every collection. Filter, sort and choose columns, then save the selection as a view."
    >
      <RecordsExplorer lockedSchema={schema.name} />
    </Page>
  )
}
