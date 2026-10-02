import { api } from './client'

export interface FileRef {
  sha256: string
  filename: string
  size: number
  volume: string
}

/** `?collection=` for an upload: the collection the file is for. */
const collectionQuery = (collectionId?: string, first = false) =>
  collectionId
    ? `${first ? '?' : '&'}collection=${encodeURIComponent(collectionId)}`
    : ''

export const filesApi = {
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
