import { useState } from 'react'
import type { Schema } from '../../api/schemas'
import { useSetUniqueKeys } from '../../hooks/useSchemas'
import { errorMessage } from '../../lib/errors'
import { displayLabel } from '../../utils/naming'
import { Button, Checkbox, Chip, EmptyState, InfoTip, Subheading } from '../ui'

/** Field types whose values compare as plain scalars (`domain/uniqueness.py`
 * is the authority; the server refuses the rest). */
const UNIQUE_TYPES = new Set([
  'integer',
  'float',
  'string',
  'boolean',
  'date',
  'datetime',
  'enum',
  'url',
  'reference',
])

/** The schema page's Uniqueness tab: combinations of fields that no two
 * records may share. A rule is checked among records of this type under the
 * same parent record (or in the same collection, for a top-level record);
 * records with a blank in the rule's fields aren't held to it. */
export function UniquenessSection({ schema }: { schema: Schema }) {
  const keys = schema.unique_keys ?? []
  const save = useSetUniqueKeys(schema.name)
  const [draft, setDraft] = useState<string[]>([])
  const eligible = schema.fields.filter((f) => UNIQUE_TYPES.has(f.type))
  const label = (name: string) => {
    const f = schema.fields.find((x) => x.name === name)
    return f ? displayLabel(f.name, f.label) : name
  }
  const describe = (key: string[]) => key.map(label).join(' + ')
  const nested = schema.parent_id !== null

  const add = () => {
    // Keep the order the fields have on the schema, however they were ticked.
    const key = eligible.map((f) => f.name).filter((n) => draft.includes(n))
    save.mutate([...keys, key], { onSuccess: () => setDraft([]) })
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Subheading>Rules</Subheading>
        {keys.length === 0 ? (
          <EmptyState
            title="No uniqueness rules"
            message="Any number of records can hold the same values."
          />
        ) : (
          <div className="flex flex-wrap gap-2">
            {keys.map((key) => (
              <Chip
                key={key.join('\u0000')}
                removeLabel={`Remove the rule ${describe(key)}`}
                onRemove={() =>
                  save.mutate(
                    keys.filter((k) => k.join('\u0000') !== key.join('\u0000')),
                  )
                }
              >
                {describe(key)}
              </Chip>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-2">
        <Subheading>
          Add a rule
          <InfoTip>
            No two {displayLabel(schema.name, schema.label)} records may have
            the same values in all of the fields you tick,{' '}
            {nested ? 'under the same parent record' : 'in the same collection'}
            . A record where any of them is blank isn’t held to the rule.
          </InfoTip>
        </Subheading>
        {eligible.length === 0 ? (
          <p className="flex items-center gap-1 text-sm text-fg-muted">
            No fields can be made unique.
            <InfoTip>
              Files, locations and lists can’t. A rule uses the schema’s own
              fields, so inherited ones aren’t listed.
            </InfoTip>
          </p>
        ) : (
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {eligible.map((f) => (
              <label key={f.name} className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={draft.includes(f.name)}
                  onChange={(e) =>
                    setDraft(
                      e.target.checked
                        ? [...draft, f.name]
                        : draft.filter((n) => n !== f.name),
                    )
                  }
                />
                {displayLabel(f.name, f.label)}
              </label>
            ))}
          </div>
        )}
        {save.error && (
          <p role="alert" className="text-sm text-danger">
            {errorMessage(save.error)}
          </p>
        )}
        <Button
          variant="primary"
          size="sm"
          disabled={draft.length === 0 || save.isPending}
          onClick={add}
        >
          {save.isPending ? 'Checking…' : 'Add rule'}
        </Button>
      </div>
    </div>
  )
}
