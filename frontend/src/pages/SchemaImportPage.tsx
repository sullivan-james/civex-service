import { useParams } from 'react-router'
import { useSchema } from '../hooks/useSchemas'
import { Page, DetailSkeleton, ErrorState } from '../components/ui'
import { errorMessage } from '../lib/errors'
import { displayLabel } from '../utils/naming'
import ImportWizard from '../components/import/ImportWizard'

export default function SchemaImportPage() {
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
        loading={<DetailSkeleton metadataRows={0} sections={1} />}
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
      breadcrumbs={[...breadcrumbs, { label: 'Import' }]}
      title="Import data"
    >
      <ImportWizard schemaId={schema.id} />
    </Page>
  )
}
