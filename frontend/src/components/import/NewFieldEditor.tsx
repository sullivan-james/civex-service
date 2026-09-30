import { Field, Input, Select } from '../ui'
import { nameError, slugify } from '../../utils/naming'
import { RESTRICTION_FREE_TYPES, type NewFieldDraft } from './importWizardTypes'

/** Compact inline editor for a not-yet-created field — name/label/type.
 * Edits a draft only; the caller decides when (and whether) to actually
 * POST it. `typeOptions` defaults to every type creatable with just
 * name/label/type (see RESTRICTION_FREE_TYPES) — pass a narrower list (e.g.
 * `['file']`) when the caller has already decided the field's role. */
export function NewFieldEditor({
  draft,
  onChange,
  typeOptions = RESTRICTION_FREE_TYPES,
}: {
  draft: NewFieldDraft
  onChange: (next: NewFieldDraft) => void
  typeOptions?: readonly string[]
}) {
  const error = draft.name ? nameError(draft.name) : 'A name is required'
  return (
    <div className="flex flex-wrap items-end gap-2 mt-1 pl-3 border-l-2 border-accent-muted">
      <Field label="Label" hideLabel span={4}>
        <Input
          size="sm"
          value={draft.label}
          onChange={(e) =>
            onChange({
              ...draft,
              label: e.target.value,
              name: slugify(e.target.value),
            })
          }
          placeholder="Field label"
        />
      </Field>
      <Field label="Name" hideLabel span={4} error={error ?? undefined}>
        <Input
          size="sm"
          className="font-mono"
          value={draft.name}
          onChange={(e) => onChange({ ...draft, name: e.target.value })}
          placeholder="field_name"
        />
      </Field>
      <Field label="Type" hideLabel span={4}>
        <Select
          size="sm"
          value={draft.type}
          onChange={(e) => onChange({ ...draft, type: e.target.value })}
        >
          {typeOptions.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </Select>
      </Field>
    </div>
  )
}
