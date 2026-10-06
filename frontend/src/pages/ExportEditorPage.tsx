import { useParams, useSearchParams } from 'react-router'
import { ExportBuilder } from '../components/exports/ExportDefinitionBuilder'
import {
  Button,
  Card,
  DetailSkeleton,
  EmptyState,
  ErrorState,
  Page,
} from '../components/ui'
import { useExportDefinitions } from '../hooks/useExportDefinitions'
import { useBack } from '../hooks/useBack'
import { useSchemas } from '../hooks/useSchemas'
import { errorMessage } from '../lib/errors'
import { schemaLevels } from '../utils/hierarchy'

/** One export, on a page of its own: `/exports/new` to make one (the kind it
 * starts from can be given as `?schema=`), `/exports/<schema>/<name>` to change
 * one. Cancelling, and finishing, go back to where the person came from, so the
 * list they left returns with its search and filters. */
export default function ExportEditorPage() {
  const { schema: fromPath, name } = useParams<{
    schema?: string
    name?: string
  }>()
  const [params] = useSearchParams()
  const back = useBack('/exports')
  const { data: schemas, isLoading: loadingSchemas, error } = useSchemas()
  const saved = useExportDefinitions(name ? fromPath : undefined)
  // Exports, then this export: the current page is the last item, as elsewhere.
  const crumbs = [
    { label: 'Exports', to: '/exports' },
    { label: name ?? 'New export' },
  ]

  if (loadingSchemas || (name && saved.isLoading))
    return (
      <Page
        breadcrumbs={crumbs}
        loading={<DetailSkeleton metadataRows={0} sections={2} />}
      />
    )
  const failure = error ?? saved.error
  if (failure)
    return (
      <Page
        breadcrumbs={crumbs}
        error={<ErrorState message={errorMessage(failure)} />}
      />
    )

  const live = (schemas ?? []).filter((s) => !s.deleted_at)
  const editing = name ? saved.data?.find((e) => e.name === name) : undefined
  if (name && !editing)
    return (
      <Page
        breadcrumbs={crumbs}
        error={
          <EmptyState
            title="That export is not here"
            message="It may have been deleted or renamed."
            action={
              <Button variant="primary" to="/exports">
                Back to exports
              </Button>
            }
          />
        }
      />
    )

  // The kind it starts from: the export's own, or the one asked for, or the top
  // of the first tree.
  const start =
    live.find(
      (s) => s.name === (editing?.schema_name ?? params.get('schema')),
    ) ?? schemaLevels(live)[0]?.schema
  if (!start)
    return (
      <Page
        breadcrumbs={crumbs}
        error={
          <EmptyState
            title="No schemas yet"
            message="An export starts from a kind of record, so make a schema first."
          />
        }
      />
    )

  return (
    <Page
      breadcrumbs={crumbs}
      title={editing ? editing.name : 'New export'}
      info="Choose what the export takes and how the folder is laid out. It starts from a kind of record and takes that kind and everything inside it."
      action={
        <Button variant="ghost" size="md" onClick={back}>
          Cancel
        </Button>
      }
    >
      <Card>
        <ExportBuilder
          // A fresh builder for each export, so nothing carries over.
          key={editing?.id ?? 'new'}
          schemas={schemas ?? []}
          attach={{ schema: start, editing }}
          onDone={back}
        />
      </Card>
    </Page>
  )
}
