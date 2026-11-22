/**
 * Where exports are saved: any folder of this computer a person chose with
 * the folder browser, remembered per browser and project. None chosen: the
 * project's own exports folder (or a drive's, for a saved export that names
 * one), as before.
 */
import { readStored } from '../hooks/useStored'

export const EXPORT_FOLDER_KEY = 'export.folder'

/** The folder chosen for exports, if any. */
export function exportFolder(): string | null {
  return readStored<string | null>(EXPORT_FOLDER_KEY, null)
}

/** The folder an export called `name` is made in, inside the chosen folder
 * (so a folder of the person's own files is never written into directly).
 * Undefined when none is chosen. */
export function exportDest(name: string): string | undefined {
  const folder = exportFolder()
  if (!folder) return undefined
  const sep = folder.includes('\\') && !folder.includes('/') ? '\\' : '/'
  const safe = name.replace(/[\\/:*?"<>|]+/g, '-').trim() || 'export'
  return folder.replace(/[\\/]+$/, '') + sep + safe
}
