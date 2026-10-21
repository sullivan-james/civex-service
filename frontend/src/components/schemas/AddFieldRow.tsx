import { useState } from 'react'
import type { FieldKind, Schema } from '../../api/schemas'
import { usePermissions } from '../../hooks/useMe'
import { Button } from '../ui'
import { Plus } from '../ui/icons'
import { fieldsWithInherited } from '../../utils/schemaFields'
import { FieldForm } from './FieldForm'
import { FieldKindPicker } from './FieldKindPicker'

/** The last row of a record form: "+ Add field", like adding a column to a
 * sheet. It expands in place into the same kind picker and field form as
 * the schema's page, and the field lands on the type (the toast says
 * so), so every record of the kind gets it. */
export function AddFieldRow({
  schema,
  allSchemas,
}: {
  schema: Schema
  allSchemas: Schema[] | undefined
}) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<FieldKind | null>(null)
  const { can, why } = usePermissions()
  const cannot = can('change_structure') ? undefined : why('change_structure')

  if (!open)
    return (
      <div className="mt-2">
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setOpen(true)}
          disabled={!!cannot}
          title={cannot}
        >
          <Plus size={14} /> Add field
        </Button>
      </div>
    )

  const close = () => {
    setOpen(false)
    setKind(null)
  }
  return (
    <div className="mt-3 rounded-md border border-border bg-canvas p-4">
      {kind ? (
        <FieldForm
          key={kind.key}
          mode="create"
          kind={kind}
          schemaName={schema.name}
          schemas={allSchemas}
          fields={fieldsWithInherited(schema, allSchemas)}
          onChangeKind={() => setKind(null)}
          onDone={close}
        />
      ) : (
        <FieldKindPicker title={null} onPick={setKind} onCancel={close} />
      )}
    </div>
  )
}
