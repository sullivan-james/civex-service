import type { ExportDefinition } from '../../api/exportDefinitions'
import type { FileSelection } from '../../api/fileAccess'
import { useSchemas } from '../../hooks/useSchemas'
import { ExportBuilder } from '../exports/ExportDefinitionBuilder'
import { Modal, ModalBody, ModalHeader } from '../ui'
import type { FlowContext } from './fileFlows'

/** An export saved with a schema, as the Files menu offers it. */
export interface MenuPreset {
  label: string
  hint: string
  /** What it takes when run where the person is (the saved export, on this record
   * or collection). */
  selection: FileSelection
  folderName: string
  /** The saved export itself, so the builder opens filled in with it. */
  definition?: ExportDefinition
}

/** The export builder, in a dialog, from wherever Files was clicked: the same
 * steps as when saving an export with a schema, finishing by choosing how to get
 * the files. A saved export opens it already filled in, at the last step. */
export function ExportDialog({
  context,
  folderName,
  scopeSchema,
  preset,
  ctx,
  onClose,
}: {
  /** Where it was asked for (a record, a collection, a list): what an export
   * here is limited to. */
  context: FileSelection
  folderName: string
  /** The kind whose tree the choices come from; none means every kind. */
  scopeSchema?: string
  preset?: MenuPreset
  ctx: FlowContext
  onClose: () => void
}) {
  const { data: schemas = [] } = useSchemas()
  return (
    <Modal onClose={onClose} size="2xl">
      <ModalHeader onClose={onClose}>
        {preset ? preset.label : 'Export files'}
      </ModalHeader>
      <ModalBody>
        <ExportBuilder
          schemas={schemas}
          scopeSchema={scopeSchema}
          run={{ context, folderName, preset, ctx }}
          onDone={onClose}
        />
      </ModalBody>
    </Modal>
  )
}
