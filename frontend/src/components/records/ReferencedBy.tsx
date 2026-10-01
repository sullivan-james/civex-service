import { Link } from 'react-router'
import { useReferrers } from '../../hooks/useRecords'
import { useSchemas } from '../../hooks/useSchemas'
import { Button, CollapsibleSection } from '../ui'
import type { ReferrerGroup } from '../../api/records'
import type { FilterTreeWire } from '../../utils/filterTree'
import { applyExplorerPatch } from '../../utils/explorerState'
import { displayLabel } from '../../utils/naming'
import { CollectionMarker } from './CollectionMarker'
import { useCollectionName } from './timeZoneContext'

/** The collection page listing a group's referrers: their schema in their
 * collection, filtered to the records whose field points at `recordId`. A
 * `reference_list` holds an array, so it's matched with `contains`; `eq`
 * would compare the whole array and never match. */
export function referrersHref(group: ReferrerGroup, recordId: string): string {
  const filter: FilterTreeWire = {
    field: group.field_name,
    op: group.dtype === 'reference_list' ? 'contains' : 'eq',
    value: recordId,
  }
  return `/collections/${group.dataset_id}?${applyExplorerPatch(
    new URLSearchParams(),
    { schema: group.schema_name, filter },
  )}`
}

function Groups({ recordId }: { recordId: string }) {
  const { data: groups, isLoading, isError } = useReferrers(recordId)
  const { data: schemas } = useSchemas()
  const currentCollection = useCollectionName()

  if (isLoading) return <p className="text-sm text-fg-muted">Loading…</p>
  if (isError)
    return <p className="text-sm text-danger">Couldn't load references.</p>
  if (!groups || groups.length === 0)
    return (
      <p className="text-sm text-fg-muted">Nothing references this record.</p>
    )

  return (
    <ul className="divide-y divide-border-muted rounded-md border border-border">
      {groups.map((g) => {
        const schema = schemas?.find((s) => s.name === g.schema_name)
        const field = schema?.fields.find((f) => f.name === g.field_name)
        return (
          <li
            key={`${g.dataset_id}/${g.schema_name}/${g.field_name}`}
            className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
          >
            <span className="text-fg">
              <span className="font-semibold">{g.count.toLocaleString()}</span>{' '}
              {displayLabel(g.schema_name, schema?.label)}
              <span className="text-fg-muted">
                {' '}
                via {displayLabel(g.field_name, field?.label)}
              </span>
              {g.collection !== currentCollection && (
                <CollectionMarker name={g.collection} />
              )}
            </span>
            <Link to={referrersHref(g, recordId)}>
              <Button size="sm">View all</Button>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

/** Reverse references: which records point at this one, per collection,
 * schema and field. Collapsed by default -- finding them scans record data,
 * so nothing is fetched until the section is opened. */
export function ReferencedBy({ recordId }: { recordId: string }) {
  return (
    <CollapsibleSection title="Referenced by">
      <Groups recordId={recordId} />
    </CollapsibleSection>
  )
}
