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
}

export interface FileRef {
  sha256: string
  filename: string
  size: number
  volume: string
  resolved_filename?: string
  location?: FileLocation | null
}

/** What `uploadStreaming` reports as it goes. */
export interface UploadInfo {
  loaded: number
  total: number
  /** Every byte is sent; the server is still saving the file. */
  saving: boolean
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

  upload: (file: File, collectionId?: string) => {
    const form = new FormData()
    form.append('file', file)
    return api.upload<FileRef>(
      `/files${collectionQuery(collectionId, true)}`,
      form,
    )
  },

  /** Streams `file`'s raw bytes directly (no multipart wrapping) so the
   * server can write straight to the object store instead of buffering the
   * whole upload first, and so `onProgress` gets real upload-progress
   * events -- `fetch()` request bodies don't expose those, only XHR does.
   *
   * `onProgress` is told the fraction sent and the bytes; once every byte is
   * sent it is called again with `saving: true`, because the server is then
   * still hashing and writing the file (which, for a large file on a slow
   * drive, takes a while the bar can't show). Aborting `signal` stops the
   * upload and rejects with an `AbortError`. */
  uploadStreaming: (
    file: File,
    onProgress?: (fraction: number, info?: UploadInfo) => void,
    collectionId?: string,
    signal?: AbortSignal,
  ): Promise<FileRef> =>
    new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(new DOMException('Upload cancelled', 'AbortError'))
        return
      }
      const xhr = new XMLHttpRequest()
      xhr.open(
        'PUT',
        `/api/files/stream?filename=${encodeURIComponent(file.name)}${collectionQuery(collectionId)}`,
      )
      xhr.upload.onprogress = (e) => {
        if (onProgress && e.lengthComputable)
          onProgress(e.loaded / e.total, {
            loaded: e.loaded,
            total: e.total,
            saving: false,
          })
      }
      xhr.upload.onload = () =>
        onProgress?.(1, { loaded: file.size, total: file.size, saving: true })
      signal?.addEventListener('abort', () => xhr.abort(), { once: true })
      xhr.onabort = () =>
        reject(new DOMException('Upload cancelled', 'AbortError'))
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText))
          } catch {
            reject(
              new Error('Upload succeeded but response was not valid JSON'),
            )
          }
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
      xhr.onerror = () => reject(new Error('Network error during upload'))
      xhr.send(file)
    }),
}
