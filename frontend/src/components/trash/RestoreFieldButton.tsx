import { useState } from 'react'
import { Button } from '../ui'
import { RestoreDialog } from './RestoreDialog'

/** "Restore…" for one deleted field: says what comes back, then does it. The
 * field is restored on `schemaName`, the schema it was defined on (which may be
 * one the record's own schema inherits from). */
export function RestoreFieldButton({
  fieldId,
  schemaName,
  size = 'sm',
}: {
  fieldId: string
  schemaName: string
  size?: 'sm' | 'md'
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button size={size} onClick={() => setOpen(true)}>
        Restore…
      </Button>
      {open && (
        <RestoreDialog
          target={{ kind: 'field', ref: fieldId, schema: schemaName }}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  )
}
