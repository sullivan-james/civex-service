import { createContext, useContext } from 'react'
import type { Field } from '../../api/schemas'
import { effectiveTimeZone } from '../../utils/dates'

/** The collection's timezone (null = unset) for everything rendered under a
 * `CollectionTimeZone` provider. A record, a record form and a table of
 * records all live in exactly one collection, so a context saves threading
 * a prop through RecordForm -> DynamicField -> EditableCell. */
export const TimeZoneContext = createContext<string | null>(null)

/** Name of the collection beneath a `CollectionTimeZone` provider, so a
 * reference picker can search only what that collection may reference. */
export const CollectionNameContext = createContext<string | null>(null)

export function useCollectionName(): string | null {
  return useContext(CollectionNameContext)
}

/** The zone this field's datetimes are shown and entered in: the field's own
 * `timezone` restriction, else the collection's, else null (viewer's zone). */
export function useFieldTimeZone(field: Field | undefined): string | null {
  const collectionTimeZone = useContext(TimeZoneContext)
  return effectiveTimeZone(field, collectionTimeZone)
}
