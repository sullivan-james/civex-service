import type { FileUpload } from '../../api/records'

/** A file chosen for a record that doesn't exist yet: held in the browser,
 * shown in its field by name and size, and sent with the record when it is
 * added (`POST /collections/{c}/records/with-files`), so nothing is stored
 * until the record is. It carries `filename` like a stored file, so what
 * reads a file's name (a from-filename preview) reads it too. */
export interface PendingFile {
  pending: true
  file: File
  filename: string
  size: number
}

export function pendingFile(file: File): PendingFile {
  return { pending: true, file, filename: file.name, size: file.size }
}

export function isPendingFile(value: unknown): value is PendingFile {
  return (
    !!value &&
    typeof value === 'object' &&
    (value as PendingFile).pending === true &&
    (value as PendingFile).file instanceof File
  )
}

/** A new record's values as the create request takes them: the pending files
 * taken out of `data` and listed by field, in order. A list left with no
 * files is left out. */
export function splitPendingFiles(data: Record<string, unknown>): {
  data: Record<string, unknown>
  files: FileUpload[]
} {
  const plain: Record<string, unknown> = {}
  const files: FileUpload[] = []
  for (const [field, value] of Object.entries(data)) {
    if (isPendingFile(value)) {
      files.push({ field, file: value.file })
    } else if (Array.isArray(value) && value.some(isPendingFile)) {
      const rest = value.filter((v) => !isPendingFile(v))
      for (const v of value)
        if (isPendingFile(v)) files.push({ field, file: v.file })
      if (rest.length) plain[field] = rest
    } else {
      plain[field] = value
    }
  }
  return { data: plain, files }
}
