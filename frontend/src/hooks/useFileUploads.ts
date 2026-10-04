import { useCallback, useRef, useState } from 'react'
import { filesApi, type FileRef } from '../api/files'

/** One upload as it is going: enough to say which file, how far, how fast and
 * how long is left, or that every byte is sent and the server is saving it. */
export interface UploadProgressState {
  /** Position in this batch, from 0. */
  index: number
  total: number
  name: string
  size: number
  loaded: number
  /** Bytes per second since this file started; 0 until there is a reading. */
  rate: number
  /** Seconds left at that rate, or null when it can't be told yet. */
  eta: number | null
  /** Every byte is sent; the server is hashing and writing the file. */
  saving: boolean
}

export interface UploadOutcome {
  /** The files that finished, in order, even if the batch was cancelled. */
  refs: FileRef[]
  cancelled: boolean
}

/** Uploads files one after another, reporting live progress and letting the
 * person stop. Cancelling keeps what had already finished: a batch of five
 * stopped during the third gives back the first two. Anything else that goes
 * wrong is thrown for the caller to show. */
export function useFileUploads(collectionId?: string) {
  const [current, setCurrent] = useState<UploadProgressState | null>(null)
  const controller = useRef<AbortController | null>(null)

  const run = useCallback(
    async (files: File[]): Promise<UploadOutcome> => {
      const abort = new AbortController()
      controller.current = abort
      const refs: FileRef[] = []
      try {
        for (let i = 0; i < files.length; i++) {
          const file = files[i]
          const started = performance.now()
          setCurrent({
            index: i,
            total: files.length,
            name: file.name,
            size: file.size,
            loaded: 0,
            rate: 0,
            eta: null,
            saving: false,
          })
          const ref = await filesApi.uploadStreaming(
            file,
            (_fraction, info) => {
              if (!info) return
              const seconds = (performance.now() - started) / 1000
              const rate = seconds > 0.25 ? info.loaded / seconds : 0
              setCurrent({
                index: i,
                total: files.length,
                name: file.name,
                size: info.total || file.size,
                loaded: info.loaded,
                rate,
                eta: rate > 0 ? (info.total - info.loaded) / rate : null,
                saving: info.saving,
              })
            },
            collectionId,
            abort.signal,
          )
          refs.push(ref)
        }
        return { refs, cancelled: false }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError')
          return { refs, cancelled: true }
        throw err
      } finally {
        controller.current = null
        setCurrent(null)
      }
    },
    [collectionId],
  )

  const cancel = useCallback(() => controller.current?.abort(), [])

  return { current, uploading: current !== null, run, cancel }
}
