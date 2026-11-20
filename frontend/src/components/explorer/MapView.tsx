import { lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router'
import { queryBody } from '../../api/records'
import type { RecordQueryParams } from '../../api/query'
import { useRecordPoints } from '../../hooks/useRecords'
import { useMapSettings } from '../../hooks/useMapSettings'
import { ErrorState, Field, Select } from '../ui'
import { errorMessage } from '../../lib/errors'
import { displayLabel } from '../../utils/naming'
import type { FilterableField } from '../../utils/hierarchy'
import { fieldKey } from '../../utils/summary'

// OpenLayers is a large chunk: only loaded when a map is shown.
const RecordsMap = lazy(() => import('../geo/RecordsMap'))

/** Address name (beside the explorer's own): the location field mapped. */
const FIELD_PARAM = 'map.f'

/** The location fields a map of the listed kind can use: its own, then those
 * of the kinds above it (each record is placed where the one above is). */
export function mapFields(fields: FilterableField[]): FilterableField[] {
  return fields.filter((f) => f.type === 'geo' && f.relation !== 'descendant')
}

/** The records the explorer lists, on a map: the same query (filter, search,
 * view, the record they are inside), by one of their location fields. */
export function MapView({
  query,
  collection,
  fields,
}: {
  query: RecordQueryParams
  collection: string | undefined
  /** The listed kind's fields and its relatives' (`filterableFields`). */
  fields: FilterableField[]
}) {
  const [params, setParams] = useSearchParams()
  const usable = mapFields(fields)
  const chosen =
    usable.find((f) => fieldKey(f) === params.get(FIELD_PARAM)) ?? usable[0]
  const settings = useMapSettings()
  const body =
    query.schema && chosen
      ? {
          ...queryBody({ ...query, sort: undefined }, collection),
          field: chosen.name,
          field_schema:
            chosen.relation === 'self' ? undefined : chosen.sourceSchemaName,
        }
      : null
  const { data, isLoading, isFetching, error } = useRecordPoints(body)

  if (!chosen)
    return (
      <p className="text-sm text-fg-muted">
        This kind of record has no location field to map.
      </p>
    )
  const label = (f: FilterableField) => {
    const own = displayLabel(f.name, f.label)
    return f.relation === 'self' ? own : `${f.sourceSchemaName} › ${own}`
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {usable.length > 1 && (
          <>
            <span className="text-sm text-fg-muted">Place by</span>
            <Field label="Location field to map" hideLabel>
              <Select
                size="sm"
                value={fieldKey(chosen)}
                onChange={(e) =>
                  setParams(
                    (prev) => {
                      const out = new URLSearchParams(prev)
                      out.set(FIELD_PARAM, e.target.value)
                      return out
                    },
                    { replace: true },
                  )
                }
              >
                {usable.map((f) => (
                  <option key={fieldKey(f)} value={fieldKey(f)}>
                    {label(f)}
                  </option>
                ))}
              </Select>
            </Field>
          </>
        )}
        {data && (
          <p className="text-sm text-fg-muted" aria-live="polite">
            {data.truncated
              ? `Showing the first ${data.points.length.toLocaleString()} of ${data.total.toLocaleString()} records with a ${label(chosen)}.`
              : data.total === 0
                ? `None of these records has a ${label(chosen)}.`
                : `${data.total.toLocaleString()} with a ${label(chosen)}.`}
          </p>
        )}
      </div>
      {error ? (
        <ErrorState message={errorMessage(error)} />
      ) : isLoading || !data ? (
        <p className="text-sm text-fg-muted">Finding where they are…</p>
      ) : (
        <div className={isFetching ? 'opacity-70' : undefined}>
          <Suspense
            fallback={<p className="text-sm text-fg-muted">Loading the map…</p>}
          >
            <RecordsMap
              points={data.points}
              tileUrl={settings?.tile_url}
              tileAttribution={settings?.attribution}
            />
          </Suspense>
        </div>
      )}
    </div>
  )
}
