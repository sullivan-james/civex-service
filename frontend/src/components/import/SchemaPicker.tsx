import { NameLabelFields, Select } from '../ui'
import { displayLabel } from '../../utils/naming'
import { NEW_SCHEMA } from './importWizardTypes'
import type { Schema } from '../../api/schemas'

/** "Which record type" chooser: pick an existing schema or create one
 * inline. Purely presentational — side effects of changing schema (e.g.
 * resetting a parent-record choice, re-running column suggestions) are the
 * caller's job, not this component's. */
export function SchemaPicker({
  schemas,
  value,
  onChange,
  isNew,
  newSchema,
  onNewSchemaChange,
}: {
  schemas: Schema[] | undefined
  value: string
  onChange: (schemaChoice: string) => void
  isNew: boolean
  newSchema: { label: string; name: string }
  onNewSchemaChange: (next: { label: string; name: string }) => void
}) {
  return (
    <div className="space-y-2">
      <span className="text-xs font-semibold text-fg-muted uppercase tracking-wide">
        Record type
      </span>
      <Select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full max-w-sm"
      >
        <option value="">— Select a record type —</option>
        <option value={NEW_SCHEMA}>+ Create a new record type</option>
        {schemas?.map((s) => (
          <option key={s.id} value={s.id}>
            {displayLabel(s.name, s.label)}
            {s.parent_id ? ' (child record)' : ''}
          </option>
        ))}
      </Select>
      {isNew && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 pt-2">
          <NameLabelFields
            kind="Schema"
            value={newSchema}
            onChange={onNewSchemaChange}
            autoFocus
          />
        </div>
      )}
    </div>
  )
}
