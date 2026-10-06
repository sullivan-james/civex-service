import type { FileSelection } from '../../api/fileAccess'
import { useExportHost } from '../../hooks/useExportHost'
import { Button, Menu } from '../ui'
import {
  Bookmark,
  ChevronDown,
  FolderTree,
  SlidersHorizontal,
  Upload,
} from '../ui/icons'
import type { MenuPreset } from './ExportDialog'

export type { MenuPreset }

/** The **Export** menu for what is being looked at. Saved exports for this kind of
 * record come first, each one a click to its dialog; below them, **Export
 * files…** for a one-time export of anything here. Both open the same dialog,
 * where how to get the files (a folder of links, copies on a drive, a zip) is a
 * choice. Where to set exports up, and the folders already made, are at the end.
 *
 * Choosing does the work in the background (the status bar shows it if it takes
 * a moment); only when something needs a decision, because files can't be reached
 * or are spread over several drives, does another dialog open. */
export function FileAccessActions({
  selection,
  folderName,
  presets = [],
  builderTo,
  scopeSchema,
  label = 'Export',
  size = 'sm',
}: {
  selection: FileSelection
  /** Names the folder on the server: the same name refreshes the same folder. */
  folderName: string
  /** The exports saved for this kind of record, offered first. */
  presets?: MenuPreset[]
  /** Where to set exports up, for this kind of record. */
  builderTo?: string
  /** The kind whose tree a one-time export chooses among; none means every kind. */
  scopeSchema?: string
  /** The button's words ('Files' where the menu is about files in general). */
  label?: string
  size?: 'sm' | 'md'
}) {
  const { navigate, openExport, dialogs } = useExportHost({
    selection,
    folderName,
    scopeSchema,
  })

  return (
    <>
      <Menu
        align="left"
        wide
        items={[
          ...(presets.length > 0
            ? [
                { heading: 'Saved exports' },
                ...presets.map((p) => ({
                  label: p.label,
                  hint: p.hint,
                  icon: Bookmark,
                  onClick: () => openExport(p),
                })),
                { separator: true as const },
              ]
            : []),
          {
            label: 'Export…',
            hint: 'Take the files, a table of the records, or both.',
            icon: Upload,
            onClick: () => openExport(),
          },
          { separator: true as const },
          ...(builderTo
            ? [
                {
                  label: 'Set up exports…',
                  hint: 'Save exports with this kind of record.',
                  icon: SlidersHorizontal,
                  onClick: () => navigate(builderTo),
                },
              ]
            : []),
          {
            label: 'Manage exports…',
            hint: 'Folders already made.',
            icon: FolderTree,
            onClick: () => navigate('/exports?tab=made'),
          },
        ]}
        trigger={({ toggle, open }) => (
          <Button
            size={size}
            aria-haspopup="menu"
            aria-expanded={open}
            onClick={toggle}
          >
            <Upload size={16} aria-hidden="true" />
            {label}
            <ChevronDown size={16} aria-hidden="true" />
          </Button>
        )}
      />
      {dialogs}
    </>
  )
}
