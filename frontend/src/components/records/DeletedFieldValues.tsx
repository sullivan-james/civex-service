import type { DeletedFieldValue } from '../../api/records'
import { AuditValue } from '../audit/AuditValue'
import { RestoreFieldButton } from '../trash/RestoreFieldButton'
import { Subheading } from '../ui'

/** Values a record still holds for fields that have been deleted from its
 * schema. They are not lost: each says when the field was deleted and can be
 * restored, which puts the value back in the form above. */
export function DeletedFieldValues({
  fields,
}: {
  fields: DeletedFieldValue[]
}) {
  if (!fields.length) return null
  return (
    <section aria-label="Deleted fields" className="mt-6 space-y-2">
      <Subheading>Deleted fields</Subheading>
      <dl className="divide-y divide-border rounded-md border border-border">
        {fields.map((f) => (
          <div
            key={f.id}
            className="grid items-start gap-1 p-3 sm:grid-cols-[10rem_1fr_auto] sm:gap-4"
          >
            <dt className="text-xs font-medium text-fg-muted">{f.label}</dt>
            <dd className="min-w-0 break-words text-sm text-fg-muted">
              <AuditValue value={f.value} dtype={f.dtype} />
              <span className="block text-xs text-attention">
                Deleted
                {f.deleted_at
                  ? ` ${new Date(f.deleted_at).toLocaleDateString()}`
                  : ''}
                . It can be restored, and this value comes back with it.
              </span>
            </dd>
            <RestoreFieldButton fieldId={f.id} schemaName={f.schema_name} />
          </div>
        ))}
      </dl>
    </section>
  )
}
