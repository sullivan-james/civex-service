import { useState } from 'react'
import type { FieldKind, Schema } from '../../api/schemas'
import { Modal, ModalBody, ModalHeader } from '../ui'
import { displayLabel } from '../../utils/naming'
import { fieldsWithInherited } from '../../utils/schemaFields'
import { FieldForm } from './FieldForm'
import { FieldKindPicker } from './FieldKindPicker'

/** Add a field to a record type from wherever its records are: the same kind
 * picker and form as the type's own page, in a dialog. The field lands on
 * the type, so the title says "every <Type>", not this record. */
export function AddFieldDialog({
  schema,
  allSchemas,
  onClose,
  onAdded,
}: {
  schema: Schema
  allSchemas: Schema[] | undefined
  onClose: () => void
  /** Called with the new field's name once it is saved. */
  onAdded?: (name: string) => void
}) {
  const [kind, setKind] = useState<FieldKind | null>(null)
  const label = displayLabel(schema.name, schema.label)
  return (
    <Modal onClose={onClose} size="lg">
      <ModalHeader>Add a field to every {label.toLowerCase()}</ModalHeader>
      <ModalBody>
        <p className="mb-4 text-sm text-fg-muted">
          A field is one box on the {label.toLowerCase()} form. Every{' '}
          {label.toLowerCase()} gets it, here and from now on.
        </p>
        {kind ? (
          <FieldForm
            key={kind.key}
            mode="create"
            kind={kind}
            schemaName={schema.name}
            schemas={allSchemas}
            fields={fieldsWithInherited(schema, allSchemas)}
            onChangeKind={() => setKind(null)}
            onDone={(savedName) => {
              if (savedName) onAdded?.(savedName)
              onClose()
            }}
          />
        ) : (
          <FieldKindPicker title={null} onPick={setKind} onCancel={onClose} />
        )}
      </ModalBody>
    </Modal>
  )
}
