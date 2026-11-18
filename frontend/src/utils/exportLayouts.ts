import type { FilesLayout } from '../api/views'

/** The layouts a person can choose: a folder for each record, or every file in
 * one folder. `grouped` is still read (an export or view saved with it keeps
 * it, and is described), but no longer offered: it differed from a folder per
 * record only at the last level, which was too fine a difference to ask about. */
export const LAYOUTS: FilesLayout[] = ['tree', 'flat']

/** A few words for a line of detail ("Contour files · all in one folder"). */
export const LAYOUT_SHORT: Record<FilesLayout, string> = {
  tree: 'a folder for each record',
  grouped: 'grouped by kind',
  flat: 'all in one folder',
}
