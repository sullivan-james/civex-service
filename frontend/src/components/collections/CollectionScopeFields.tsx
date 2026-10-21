import { Field, Select } from '../ui'
import type { CollectionScope } from '../../api/collections'

/** The scope input, shared by the create and edit forms. */
export function CollectionScopeFields({
  scope,
  onScopeChange,
}: {
  scope: CollectionScope
  onScopeChange: (scope: CollectionScope) => void
}) {
  return (
    <>
      <Field
        label="Scope"
        info="Local: only records in this collection can reference its records. Global: records in any collection can — use it for shared reference data such as species or sites."
      >
        <Select
          value={scope}
          onChange={(e) => onScopeChange(e.target.value as CollectionScope)}
          className="w-full"
        >
          <option value="local">Local — private to this collection</option>
          <option value="global">Global — referenceable from anywhere</option>
        </Select>
      </Field>
    </>
  )
}
