import { useMemo, useState } from 'react'
import { errorMessage } from '../../lib/errors'
import type { Schema } from '../../api/schemas'
import { useUpdateSchema } from '../../hooks/useSchemas'
import { Button } from '../ui'
import { fieldsWithInherited } from '../../utils/schemaFields'
import { NON_NAMEABLE } from '../../utils/templates'
import {
  TemplateBuilder,
  type TemplateField,
} from '../templates/TemplateBuilder'

/** The schema page's Naming tab: the template that names this type's records. */
export function NamingSection({
  schema,
  allSchemas,
}: {
  schema: Schema
  allSchemas: Schema[] | undefined
}) {
  const saved = schema.display_template ?? ''
  const [draft, setDraft] = useState(saved)
  const update = useUpdateSchema(schema.name)
  const fields = useMemo(
    () => fieldsWithInherited(schema, allSchemas),
    [schema, allSchemas],
  )
  const dirty = draft !== saved
  // With no template, records use their first value: say which field that is.
  const firstValue = fields.find((f) => !NON_NAMEABLE.has(f.dtype))
  const placeholder = firstValue
    ? `First value, currently {${firstValue.name}}`
    : 'Add a field to name records'

  return (
    <div className="space-y-3">
      <TemplateBuilder
        schemaName={schema.name}
        kind="record"
        value={draft}
        onChange={setDraft}
        fields={fields}
        label="Record name"
        placeholder={placeholder}
      />
      {update.error && (
        <p role="alert" className="text-xs text-danger">
          {errorMessage(update.error)}
        </p>
      )}
      <div className="flex gap-2">
        <Button
          variant="primary"
          size="sm"
          disabled={!dirty || update.isPending}
          onClick={() => update.mutate({ display_template: draft.trim() })}
        >
          {update.isPending ? 'Saving…' : 'Save'}
        </Button>
        {dirty && (
          <Button size="sm" onClick={() => setDraft(saved)}>
            Discard changes
          </Button>
        )}
      </div>
    </div>
  )
}
