import type { FileSelection } from '../../api/fileAccess'
import { useExportHost } from '../../hooks/useExportHost'
import { Button } from '../ui'
import type { MenuPreset } from './ExportDialog'

/** A plain button that opens the export builder: for a saved export (filled in,
 * at its last step) or, with none, a one-time export of what is here. For a row
 * that is about one thing, where the Files menu would be too much. */
export function ExportButton({
  selection,
  folderName,
  preset,
  scopeSchema,
  label = 'Export…',
  size = 'md',
}: {
  /** Where it is asked for: what an export here is limited to. */
  selection: FileSelection
  folderName: string
  preset?: MenuPreset
  scopeSchema?: string
  label?: string
  size?: 'sm' | 'md'
}) {
  const { openExport, dialogs } = useExportHost({
    selection,
    folderName,
    scopeSchema,
  })
  return (
    <>
      <Button size={size} onClick={() => openExport(preset)}>
        {label}
      </Button>
      {dialogs}
    </>
  )
}
