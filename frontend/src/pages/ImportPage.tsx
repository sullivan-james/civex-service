import { useParams } from 'react-router'
import { useCollection } from '../hooks/useCollections'
import { Page, DetailSkeleton, ErrorState } from '../components/ui'
import { errorMessage } from '../lib/errors'
import ImportWizard from '../components/import/ImportWizard'

export default function ImportPage() {
  const { id } = useParams<{ id: string }>()
  const { data: collection, isLoading, error } = useCollection(id!)

  const breadcrumbs = [
    { label: 'Collections', to: '/collections' },
    ...(collection
      ? [{ label: collection.name, to: `/collections/${id}` }]
      : []),
  ]

  if (isLoading)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        loading={<DetailSkeleton metadataRows={0} sections={1} />}
      />
    )
  if (error || !collection)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        error={
          <ErrorState
            message={error ? errorMessage(error) : 'Collection not found'}
          />
        }
      />
    )

  return (
    <Page
      breadcrumbs={[...breadcrumbs, { label: 'Import' }]}
      title="Guided import"
      description={`Bring files or a spreadsheet into "${collection.name}" as records.`}
    >
      <ImportWizard datasetName={collection.name} />
    </Page>
  )
}
