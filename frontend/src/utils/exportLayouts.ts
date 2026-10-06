import type { FilesLayout } from '../api/views'
import type { TreeRow } from './fileTree'

export const LAYOUTS: FilesLayout[] = ['tree', 'grouped', 'flat']

/** How a layout is named to a person. */
export const LAYOUT_NAME: Record<FilesLayout, string> = {
  tree: 'A folder per record',
  grouped: 'Grouped by kind',
  flat: 'All in one folder',
}

/** A few words for a line of detail ("Contour files · all in one folder"). */
export const LAYOUT_SHORT: Record<FilesLayout, string> = {
  tree: 'a folder per record',
  grouped: 'grouped by kind',
  flat: 'all in one folder',
}

/** One line of a layout drawn as a tree (see `TreeRow`). */
export type LayoutNode = TreeRow

const folder = (depth: number, name: string): LayoutNode => ({
  depth,
  kind: 'folder',
  name,
})
const file = (depth: number, name: string): LayoutNode => ({
  depth,
  kind: 'file',
  name,
})

/** What each layout looks like, in neutral names that fit any data: a folder for
 * every level, the last level gathered into one folder, or just the files.
 * Where several records share a folder, each file is named for the record that
 * owns it ("Item 1 - file.txt"); in a folder per record it needn't be. */
export function layoutNodes(layout: FilesLayout): LayoutNode[] {
  if (layout === 'flat')
    return [
      file(0, 'Item 1 - file.txt'),
      file(0, 'Item 2 - file.txt'),
      file(0, 'Item 3 - file.txt'),
    ]
  const top = [folder(0, 'Parent 1'), folder(1, 'Child 1')]
  if (layout === 'grouped')
    return [
      ...top,
      folder(2, 'Items'),
      file(3, 'Item 1 - file.txt'),
      file(3, 'Item 2 - file.txt'),
    ]
  return [
    ...top,
    folder(2, 'Item 1'),
    file(3, 'file.txt'),
    folder(2, 'Item 2'),
    file(3, 'file.txt'),
  ]
}
