import { useRecordName } from '../../hooks/useRecordName'

/** A record's name, live, from its id. `fallback` is what to show while it
 * loads or when the record can't be found (for older data that kept a name, or
 * nothing at all); with neither, the start of the id. A record in Recently
 * Deleted says so. */
export function RecordName({
  id,
  fallback,
}: {
  id: string
  fallback?: string | null
}) {
  const { data } = useRecordName(id)
  const name = data?.natural_name ?? fallback ?? `${id.slice(0, 8)}…`
  return (
    <>
      {name}
      {data?.deleted && <span className="text-fg-subtle"> (deleted)</span>}
    </>
  )
}
