import { Link } from 'react-router'
import { useAvailableExports } from '../../hooks/useExportDefinitions'
import { useSchemas } from '../../hooks/useSchemas'
import { errorMessage } from '../../lib/errors'
import { describeDefinition } from '../../utils/exportBuilder'
import { Card, EmptyState, ErrorState, Spinner } from '../ui'
import { ExportsList } from '../files/ExportsList'
import { ExportButton } from '../files/ExportButton'
import { definitionPreset } from './exportPresets'

/** Run an export on this collection. The definitions come from its schemas (they
 * are set up there, like fields); here they are just run, and the folders they
 * make are looked after. */
export function CollectionExportsSection({
  collection,
}: {
  collection: string
}) {
  const { data, isLoading, error } = useAvailableExports({ collection })
  const { data: schemas } = useSchemas()
  const list = data ?? []

  return (
    <div className="space-y-4">
      <Card title="Exports" count={list.length + 1}>
        {isLoading && <Spinner />}
        {error != null && <ErrorState message={errorMessage(error)} />}
        <ul className="divide-y divide-border">
          <li className="flex items-center justify-between gap-4 py-4">
            <div className="min-w-0">
              <p className="text-base font-medium text-fg">All files</p>
              <p className="text-sm text-fg-muted">A folder per record</p>
            </div>
            <ExportButton
              selection={{ collection }}
              folderName={`${collection}-files`}
            />
          </li>
          {list.map((d) => (
            <li
              key={d.id}
              className="flex items-center justify-between gap-4 py-4"
            >
              <div className="min-w-0">
                <p className="truncate text-base font-medium text-fg">
                  {d.name}
                </p>
                <p className="text-sm text-fg-muted">
                  {describeDefinition(d, schemas)} ·{' '}
                  <Link
                    to={`/exports?schema=${encodeURIComponent(d.schema_name)}`}
                    className="text-accent hover:underline"
                  >
                    starts from {d.schema_name}
                  </Link>
                </p>
              </div>
              <ExportButton
                selection={{ collection }}
                folderName={`${collection}-${d.name}`}
                preset={definitionPreset(d, collection, schemas)}
              />
            </li>
          ))}
        </ul>
        {!isLoading && list.length === 0 && (
          <EmptyState
            title="No saved exports"
            message="Set them up on the Exports page."
          />
        )}
      </Card>
      <ExportsList />
    </div>
  )
}
