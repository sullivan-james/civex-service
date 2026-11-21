import { useFieldIndex, useSetFieldIndex } from '../../hooks/useFieldIndex'
import { useHasFeature } from '../../hooks/useFeatures'
import { usePermissions } from '../../hooks/useMe'
import { errorMessage } from '../../lib/errors'
import { CheckRow } from '../ui'

const EXPLAIN =
  'Makes sorting and filtering by this field faster on this computer, and ' +
  'saving records of this kind slightly slower. A setting of this ' +
  "computer's database: it isn't shared with other devices. Built in the " +
  'background; lists work meanwhile, only slower.'

/** The field's "Indexed" switch. Takes effect at once (it is not part of the
 * form's Save): the server builds or drops the index in the background. A
 * field in a uniqueness key is always indexed, so the box is on and locked. */
export function FieldIndexRow({
  schemaName,
  fieldName,
}: {
  schemaName: string
  fieldName: string
}) {
  const has = useHasFeature()
  const { can, why } = usePermissions()
  const offered = has('db_admin')
  const { data } = useFieldIndex(schemaName, fieldName, offered)
  const set = useSetFieldIndex(schemaName, fieldName)
  if (!offered || !data || !data.indexable) return null

  const locked = data.reasons.includes('unique_key')
  const allowed = can('change_structure')
  const building = data.indexed && !data.built
  const description = locked
    ? `${EXPLAIN} Always on for a field in a uniqueness key.`
    : EXPLAIN
  return (
    <div title={!allowed ? why('change_structure') : undefined}>
      <CheckRow
        compact
        title={building ? 'Indexed (building…)' : 'Indexed'}
        description={description}
        checked={data.indexed}
        disabled={locked || !allowed || set.isPending}
        onChange={(on) => set.mutate(on)}
      />
      {set.error && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {errorMessage(set.error)}
        </p>
      )}
    </div>
  )
}
