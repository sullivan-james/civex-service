import { api } from './client'

/** Where a file is stored, stamped on file values in record responses. */
export interface FileLocation {
  /** The volume holding it; null when it isn't on any volume Civex knows. */
  volume: string | null
  /** `remote`: another device added it and it isn't on this computer yet;
   * opening or exporting it downloads it from the server. */
  state:
    | 'online'
    | 'offline'
    | 'wrong_drive'
    | 'readonly'
    | 'retired'
    | 'unknown'
    | 'remote'
  /** Can be opened right now; null when unknown. */
  available: boolean | null
  /** Why it can't be opened, in plain words (blank when it can). */
  reason?: string
  /** What to do about it, e.g. which drive to plug in (blank when nothing). */
  fix?: string
  /** `false`: on this computer, but the server hasn't said it holds it, so
   * other computers can't open it yet. Absent when it has, or when the project
   * doesn't sync. */
  sent?: false
}

export interface FileRef {
  sha256: string
  filename: string
  size: number
  volume: string
  resolved_filename?: string
  location?: FileLocation | null
}

/** Adding a file failed because the connection to civex dropped or timed
 * out, not because civex refused it: trying again can help. */
export class UploadConnectionError extends Error {}

/** What `uploadBatch` reports as it goes. */
export interface UploadInfo {
  loaded: number
  total: number
  /** Every byte is sent; the server is still saving the file. */
  saving: boolean
}

/** What `PUT /files/batch` answers: the files stored, in order, and where it
 * stopped if one couldn't be stored. */
export interface BatchResult {
  files: FileRef[]
  stopped: { index: number; message: string } | null
}

/** Most files, and most bytes, sent in one request. A file larger than the
 * byte limit goes in a request of its own. */
export const BATCH_FILES = 64
export const BATCH_BYTES = 256 * 1024 * 1024

/** A selection split into requests: in order, each at most `BATCH_FILES`
 * files and `BATCH_BYTES` (or one larger file alone). */
export function fileBatches<T>(
  files: T[],
  maxFiles = BATCH_FILES,
  maxBytes = BATCH_BYTES,
  sizeOf: (item: T) => number = (item) => (item as { size: number }).size,
): T[][] {
  const batches: T[][] = []
  let batch: T[] = []
  let bytes = 0
  for (const file of files) {
    if (
      batch.length &&
      (batch.length >= maxFiles || bytes + sizeOf(file) > maxBytes)
    ) {
      batches.push(batch)
      batch = []
      bytes = 0
    }
    batch.push(file)
    bytes += sizeOf(file)
  }
  if (batch.length) batches.push(batch)
  return batches
}

export interface FileCopy {
  volume: string
  /** Where the object is, or would be, on that volume. */
  path: string
  /** null: recorded there, but the volume can't be checked now. */
  present: boolean | null
  state: string
  network: boolean
  /** Live records whose file is this copy (each points at one). */
  records: number
}

/** Where a file's content is stored and what uses it. */
export interface FileInfo {
  sha256: string
  size: number | null
  copies: FileCopy[]
  records: number
  jobs: number
  collections: { id: string; name: string | null; records: number }[]
  /** The live records that use it, named, with the records above each
   * (at most 200; `records` is the full count). */
  /** Deleted records that still reference it: they keep it while they can
   * be restored, but don't count as using it. */
  deleted_records?: number
  uses?: {
    id: string
    name: string
    collection: string | null
    trail: string[]
  }[]
}

/** `?collection=` for an upload: the collection the file is for. */
const collectionQuery = (collectionId?: string, first = false) =>
  collectionId
    ? `${first ? '?' : '&'}collection=${encodeURIComponent(collectionId)}`
    : ''

export const filesApi = {
  info: (sha256: string) => api.get<FileInfo>(`/files/${sha256}/info`),

  /** Adds files to civex in one streamed request (`PUT /files/batch`): a
   * line listing their names and sizes, then their bytes back to back, so
   * the server writes each straight to storage and many files cost one
   * request. The body is a `Blob` of the `File`s, which the browser reads
   * from disk as it sends (nothing is copied into memory). Use `fileBatches`
   * to split a selection into requests of a sensible size.
   *
   * `onProgress` is told the bytes sent of the files (not counting the list);
   * once every byte is sent it is called again with `saving: true`, because
   * the server is still hashing and writing the last file. A file the server
   * couldn't store ends the batch: the answer holds those before it and
   * `stopped` says which and why. A dropped connection rejects with an
   * `UploadConnectionError`; aborting `signal` with an `AbortError`. */
  uploadBatch: (
    files: File[],
    onProgress?: (info: UploadInfo) => void,
    collectionId?: string,
    signal?: AbortSignal,
  ): Promise<BatchResult> =>
    new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(new DOMException('Upload cancelled', 'AbortError'))
        return
      }
      const list = new TextEncoder().encode(
        JSON.stringify(files.map((f) => ({ name: f.name, size: f.size }))) +
          '\n',
      )
      const total = files.reduce((n, f) => n + f.size, 0)
      const sent = (loaded: number) =>
        Math.min(total, Math.max(0, loaded - list.length))
      const xhr = new XMLHttpRequest()
      xhr.open('PUT', `/api/files/batch${collectionQuery(collectionId, true)}`)
      xhr.upload.onprogress = (e) =>
        onProgress?.({ loaded: sent(e.loaded), total, saving: false })
      xhr.upload.onload = () =>
        onProgress?.({ loaded: total, total, saving: true })
      signal?.addEventListener('abort', () => xhr.abort(), { once: true })
      xhr.onabort = () =>
        reject(new DOMException('Upload cancelled', 'AbortError'))
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText))
          } catch {
            reject(new Error('civex sent an answer that could not be read'))
          }
        } else if (xhr.status === 502 || xhr.status === 504) {
          // A proxy in front of civex (the dev server) couldn't reach it.
          reject(
            new UploadConnectionError(`Couldn't reach civex (${xhr.status})`),
          )
        } else {
          let detail = `HTTP ${xhr.status}`
          try {
            detail = JSON.parse(xhr.responseText)?.detail ?? detail
          } catch {
            /* response body wasn't JSON */
          }
          reject(new Error(detail))
        }
      }
      xhr.onerror = () =>
        reject(
          new UploadConnectionError(
            'The connection to civex dropped while adding the files',
          ),
        )
      xhr.send(new Blob([list, ...files]))
    }),
}
