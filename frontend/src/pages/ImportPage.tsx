import { useParams, useSearchParams } from 'react-router'
import { useCollection, useCollections } from '../hooks/useCollections'
import { usePermissions } from '../hooks/useMe'
import { ImportWizard } from '../components/import/ImportWizard'
import { DetailSkeleton, ErrorState, Page } from '../components/ui'
import { errorMessage } from '../lib/errors'

/** "Import spreadsheet": a full page for bringing a CSV or Excel file in as
 * records. At `/collections/:id/import` it goes into that collection; at
 * `/import` the collection is chosen on the page, or made from the file (the
 * way in for a project with nothing in it). `?schema=` names the kind the list
 * it was reached from was showing. */
export default function ImportPage() {
  const { id } = useParams<{ id: string }>()
  const [params] = useSearchParams()
  const one = useCollection(id ?? '')
  const all = useCollections()
  const { can, why, canSomewhere } = usePermissions()
  const collection = id ? one.data : undefined
  const loading = id ? one.isLoading : all.isLoading
  const error = id ? one.error : all.error
  const allowed = id
    ? can('write_records', collection?.id)
    : canSomewhere('write_records') && can('change_structure')

  return (
    <Page
      breadcrumbs={[
        { label: 'Collections', to: '/collections' },
        ...(collection
          ? [{ label: collection.name, to: `/collections/${id}` }]
          : []),
        { label: 'Import spreadsheet' },
      ]}
      loading={loading ? <DetailSkeleton /> : undefined}
      error={
        error ? (
          <ErrorState message={errorMessage(error)} />
        ) : !loading && (id ? collection : true) && !allowed ? (
          <ErrorState
            message={
              id || can('change_structure')
                ? why('write_records')
                : why('change_structure')
            }
          />
        ) : undefined
      }
    >
      {(id ? collection : all.data) && (
        <ImportWizard
          collection={collection?.name}
          collectionId={collection?.id}
          collections={(all.data ?? []).map((c) => c.name)}
          initialKind={params.get('schema')}
          recordsHref={(kind, name) =>
            `/collections/${encodeURIComponent(name)}?${new URLSearchParams({ schema: kind })}`
          }
        />
      )}
    </Page>
  )
}
