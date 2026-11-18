import type { FileRef } from '../api/files'

/** The files in a `file` or `file_list` value: one, a list, or none. */
export function fileRefsIn(value: unknown): FileRef[] {
  const items = Array.isArray(value) ? value : value ? [value] : []
  return items.filter(isFileRef)
}

export function isFileRef(value: unknown): value is FileRef {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { sha256?: unknown }).sha256 === 'string'
  )
}
