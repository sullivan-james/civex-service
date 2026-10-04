import type { NavTarget } from '../utils/pins'
import { useCollections } from './useCollections'
import { useRecordName } from './useRecordName'

const RECORD_PREFIX = 'record:'
const COLLECTION_PREFIX = 'collection:'

/** What to call a pinned or recent thing. A pin keeps only an id and the label
 * it had when pinned, which goes stale on a rename, so a record is named from
 * the record as it is now and a collection from the collection list (already
 * loaded for the whole app). The stored label shows until that is known, and
 * always for anything else (a saved filter or a place, whose label is theirs). */
export function useTargetLabel(target: NavTarget): string {
  const recordId =
    target.kind === 'record' && target.key.startsWith(RECORD_PREFIX)
      ? target.key.slice(RECORD_PREFIX.length)
      : null
  const collectionId =
    target.kind === 'collection' && target.key.startsWith(COLLECTION_PREFIX)
      ? target.key.slice(COLLECTION_PREFIX.length)
      : null
  const { data: record } = useRecordName(recordId)
  const { data: collections } = useCollections()

  if (recordId) return record?.natural_name ?? target.label
  if (collectionId && Array.isArray(collections))
    return collections.find((c) => c.id === collectionId)?.name ?? target.label
  return target.label
}
