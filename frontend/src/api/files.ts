import { api } from './client'

/** Where a file is stored, stamped on file values in record responses. */
export interface FileLocation {
  /** The volume holding it; null when it isn't on any volume Civex knows. */
  volume: string | null
  state:
    'online' | 'offline' | 'wrong_drive' | 'readonly' | 'retired' | 'unknown'
  /** Can be opened right now; null when unknown. */
  available: boolean | null
}

export interface FileRef {
  sha256: string
  filename: string
  size: number
  volume: string
  resolved_filename?: string
  location?: FileLocation | null
}

export interface FileCopy {
  volume: string
  /** Where the object is, or would be, on that volume. */
  path: string
  /** null: recorded there, but the volume can't be checked now. */
  present: boolean | null
  state: string
  network: boolean
}

/** Where a file's content is stored and what uses it. */
export interface FileInfo {
  sha256: string
  size: number | null
  copies: FileCopy[]
  records: number
  jobs: number
  collections: { id: string; name: string | null; records: number }[]
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
   * events -- `fetch()` request bodies don't expose those, only XHR does. */
  uploadStreaming: (
    file: File,
    onProgress?: (fraction: number) => void,
    collectionId?: string,
  ): Promise<FileRef> =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open(
        'PUT',
        `/api/files/stream?filename=${encodeURIComponent(file.name)}${collectionQuery(collectionId)}`,
      )
      xhr.upload.onprogress = (e) => {
        if (onProgress && e.lengthComputable) onProgress(e.loaded / e.total)
      }
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
