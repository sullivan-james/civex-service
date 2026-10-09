import { useCallback, useRef, useState } from 'react'
import { filesApi, UploadConnectionError, type FileRef } from '../api/files'

/** One file being added as it goes: enough to say which file, how far, how
 * fast and how long is left, or that every byte is in and civex is saving it. */
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
  /** Every byte is in; civex is hashing and writing the file. */
  saving: boolean
}

/** A batch that stopped part way: what went wrong, on which file, and the
 * files from that one on, so they can be added again. */
export interface UploadStop {
  name: string
  message: string
  rest: File[]
  /** How many of the batch were added before it stopped. */
  added: number
  total: number
}

export interface UploadOutcome {
  /** The files that finished, in order, even if the batch stopped. */
  refs: FileRef[]
  cancelled: boolean
  /** Set when a file couldn't be added (after trying it again). */
  stopped: UploadStop | null
}

/** Waits before trying a file again after the connection dropped. */
export const RETRY_DELAYS_MS = [1000, 3000]

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms)
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        reject(new DOMException('Upload cancelled', 'AbortError'))
      },
      { once: true },
    )
  })
}

/** Adds files to civex one after another, reporting live progress and letting
 * the person stop. Nothing is lost when a batch stops: cancelling keeps what
 * had finished, a dropped connection is tried again (`RETRY_DELAYS_MS`), and a
 * file that still can't be added stops the batch with `stopped` saying why and
 * holding the rest, so the caller saves what finished and offers the rest
 * again. Every caller does that through `UploadStopped`. */
export function useFileUploads(collectionId?: string) {
  const [current, setCurrent] = useState<UploadProgressState | null>(null)
  const [stopped, setStopped] = useState<UploadStop | null>(null)
  const controller = useRef<AbortController | null>(null)

  const run = useCallback(
    async (files: File[]): Promise<UploadOutcome> => {
      const abort = new AbortController()
      controller.current = abort
      setStopped(null)
      const refs: FileRef[] = []

      async function add(file: File, i: number): Promise<FileRef> {
        for (let attempt = 0; ; attempt++) {
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
          try {
            return await filesApi.uploadStreaming(
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
          } catch (err) {
            const again =
              err instanceof UploadConnectionError &&
              attempt < RETRY_DELAYS_MS.length
            if (!again) throw err
            await wait(RETRY_DELAYS_MS[attempt], abort.signal)
          }
        }
      }

      try {
        for (let i = 0; i < files.length; i++) {
          try {
            refs.push(await add(files[i], i))
          } catch (err) {
            if (err instanceof DOMException && err.name === 'AbortError')
              throw err
            const stop: UploadStop = {
              name: files[i].name,
              message: err instanceof Error ? err.message : String(err),
              rest: files.slice(i),
              added: refs.length,
              total: files.length,
            }
            setStopped(stop)
            return { refs, cancelled: false, stopped: stop }
          }
        }
        return { refs, cancelled: false, stopped: null }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError')
          return { refs, cancelled: true, stopped: null }
        throw err
      } finally {
        controller.current = null
        setCurrent(null)
      }
    },
    [collectionId],
  )

  const cancel = useCallback(() => controller.current?.abort(), [])
  const dismiss = useCallback(() => setStopped(null), [])

  return { current, uploading: current !== null, run, cancel, stopped, dismiss }
}
