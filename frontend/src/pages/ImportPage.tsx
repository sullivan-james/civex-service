import { useParams, useSearchParams } from 'react-router'
import { useCollection } from '../hooks/useCollections'
import { usePermissions } from '../hooks/useMe'
import { ImportWizard } from '../components/import/ImportWizard'
import { DetailSkeleton, ErrorState, Page } from '../components/ui'
import { errorMessage } from '../lib/errors'

/** "Import spreadsheet": a full page for bringing a CSV or Excel file into a
 * collection as records. Reached from the records list's New menu, with
 * `?schema=` naming the kind that list was showing. */
export default function ImportPage() {
  const { id } = useParams<{ id: string }>()
  const [params] = useSearchParams()
  const { data: collection, isLoading, error } = useCollection(id!)
  const { can, why } = usePermissions()
  const allowed = can('write_records', collection?.id)

  return (
    <Page
      breadcrumbs={[
        { label: 'Collections', to: '/collections' },
        ...(collection
          ? [{ label: collection.name, to: `/collections/${id}` }]
          : []),
        { label: 'Import spreadsheet' },
      ]}
      loading={isLoading ? <DetailSkeleton /> : undefined}
      error={
        error ? (
          <ErrorState message={errorMessage(error)} />
        ) : collection && !allowed ? (
          <ErrorState message={why('write_records')} />
        ) : undefined
      }
    >
      {collection && (
        <ImportWizard
          collection={collection.name}
          collectionId={collection.id}
          initialKind={params.get('schema')}
          recordsHref={(kind) =>
            `/collections/${id}?${new URLSearchParams({ schema: kind })}`
          }
        />
      )}
    </Page>
  )
}
