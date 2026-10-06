import type { FilesLayout } from '../../api/views'
import { LAYOUT_NAME, layoutNodes } from '../../utils/exportLayouts'
import { FileTree } from './FileTree'

/** A layout drawn as the folder tree it makes, so the difference between
 * layouts is seen, not read. */
export function LayoutPreview({ layout }: { layout: FilesLayout }) {
  return (
    <FileTree
      rows={layoutNodes(layout)}
      label={`${LAYOUT_NAME[layout]} example`}
      className="rounded-md bg-canvas p-3"
    />
  )
}
