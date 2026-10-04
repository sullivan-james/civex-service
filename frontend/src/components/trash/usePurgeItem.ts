import type { RestoreTarget } from '../../api/restore'
import { usePurgeCollection } from '../../hooks/useCollections'
import { usePurgeRecord } from '../../hooks/useRecords'
import { usePurgeSchema } from '../../hooks/useSchemas'

/** Delete a deleted thing permanently, by what kind of thing it is. */
export function usePurgeItem(): (target: RestoreTarget) => void {
  const schema = usePurgeSchema()
  const collection = usePurgeCollection()
  const record = usePurgeRecord()
  return ({ kind, ref }) => {
    if (kind === 'schema') schema.mutate(ref)
    else if (kind === 'collection') collection.mutate(ref)
    else record.mutate(ref)
  }
}
