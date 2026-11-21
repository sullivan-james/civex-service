import { lazy, Suspense } from 'react'
import { useSearchParams } from 'react-router'
import type { RecordSelectionBody } from '../../api/records'
import { useRecordPoints } from '../../hooks/useRecords'
import { useMapSettings } from '../../hooks/useMapSettings'
import { ErrorState, Field, Select, Skeleton } from '../ui'
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

/** Records on a map, by one of their location fields: the ones `records`
 * names (a list's own query, or an Analytics card's). `field` fixes the
 * field (a chart's, `kind.field` for a kind above); without it the first is
 * used and, opened large, another can be picked. `compact` is the size of a
 * card. Clicking a point opens its record. */
export function MapView({
  records,
  fields,
  field,
  compact = false,
}: {
  records: RecordSelectionBody
  /** The listed kind's fields and its relatives' (`filterableFields`). */
  fields: FilterableField[]
  field?: string | null
  compact?: boolean
}) {
  const [params, setParams] = useSearchParams()
  const usable = mapFields(fields)
  const wanted = (compact ? null : params.get(FIELD_PARAM)) ?? field
  const chosen = usable.find((f) => fieldKey(f) === wanted) ?? usable[0]
  const settings = useMapSettings()
  const body =
    records.schema_name && chosen
      ? {
          ...records,
          field: chosen.name,
          field_schema:
            chosen.relation === 'self' ? undefined : chosen.sourceSchemaName,
        }
      : null
  const { data, isLoading, isFetching, error } = useRecordPoints(body)

  if (!chosen) return <p className="text-sm text-fg-muted">No location field</p>
  const label = (f: FilterableField) => {
    const own = displayLabel(f.name, f.label)
    return f.relation === 'self' ? own : `${f.sourceSchemaName} › ${own}`
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {usable.length > 1 && !compact && (
          <Field label="Location field" hideLabel>
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
        )}
        {data && (
          <p className="text-sm text-fg-muted" aria-live="polite">
            {data.truncated
              ? `First ${data.points.length.toLocaleString()} of ${data.total.toLocaleString()}`
              : `${data.total.toLocaleString()} with a ${label(chosen).toLowerCase()}`}
          </p>
        )}
      </div>
      {error ? (
        <ErrorState message={errorMessage(error)} />
      ) : isLoading || !data ? (
        <Skeleton className={compact ? 'h-48' : 'h-[28rem]'} />
      ) : (
        <div className={isFetching ? 'opacity-70' : undefined}>
          <Suspense
            fallback={<Skeleton className={compact ? 'h-48' : 'h-[28rem]'} />}
          >
            <RecordsMap
              points={data.points}
              tileUrl={settings?.tile_url}
              tileAttribution={settings?.attribution}
              height={compact ? 'h-48' : undefined}
            />
          </Suspense>
        </div>
      )}
    </div>
  )
}
