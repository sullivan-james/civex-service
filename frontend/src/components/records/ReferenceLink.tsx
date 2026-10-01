import { Link } from 'react-router'
import { useRecord } from '../../hooks/useRecords'
import { CollectionMarker } from './CollectionMarker'

export function referenceLabel(
  id: string,
  labels?: Record<string, string | null> | null,
): string {
  return labels?.[id] ?? id.slice(0, 8)
}

function LinkedId({
  id,
  label,
  collection,
}: {
  id: string
  label: string | undefined
  /** Set when the target lives in a different (global) collection. */
  collection?: string
}) {
  return (
    <>
      <Link to={`/records/${id}`} className="text-accent hover:underline">
        {label ?? <span className="font-mono">{id.slice(0, 8)}</span>}
      </Link>
      {collection && <CollectionMarker name={collection} />}
    </>
  )
}

/** Reference value -> link to the target record, using a label the caller
 * already has (the server-resolved `reference_labels` on a record
 * response). Deliberately does not fetch — that keeps this the safe default
 * for tables/lists, where a self-fetching version per cell would fan out
 * into one request per row. For the one place that has no pre-resolved
 * label (the audit log, reading historical snapshots), use
 * `FetchedReferenceLink` instead. */
export function ReferenceLink({
  id,
  labels,
  collections,
}: {
  id: string
  labels?: Record<string, string | null> | null
  /** id -> collection name, for targets outside the record's own collection. */
  collections?: Record<string, string> | null
}) {
  return (
    <LinkedId
      id={id}
      label={labels?.[id] ?? undefined}
      collection={collections?.[id]}
    />
  )
}

/** Self-fetching variant for contexts with no pre-resolved label -- only
 * the audit log, which renders historical diffs the server hasn't attached
 * `reference_labels` to. Uses the same cached `useRecord` query every other
 * reference to this id anywhere on the page already shares. */
export function FetchedReferenceLink({ id }: { id: string }) {
  const { data } = useRecord(id)
  return <LinkedId id={id} label={data?.natural_name ?? undefined} />
}
