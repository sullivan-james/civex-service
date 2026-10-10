import { useCallback, useRef, useState } from 'react'
import {
  fileBatches,
  filesApi,
  UploadConnectionError,
  type FileRef,
} from '../api/files'

/** Files being added, as it goes: which file is going in, and how far the
 * whole selection has got (bytes, speed, time left), or that every byte is in
 * and civex is saving the last of a batch. */
export interface UploadProgressState {
  /** The file going in now, from 0, of `total`. */
  index: number
  total: number
  name: string
  /** Bytes of the whole selection, and how many are in. */
  size: number
  loaded: number
  /** Bytes per second since the selection started; 0 until there is a reading. */
  rate: number
  /** Seconds left at that rate, or null when it can't be told yet. */
  eta: number | null
  /** Every byte of a batch is in; civex is hashing and writing it. */
  saving: boolean
}

/** A selection that stopped part way: what went wrong, on which file, and the
 * files from that one on, so they can be added again. */
export interface UploadStop {
  name: string
  message: string
  rest: File[]
  /** How many of the selection were added before it stopped. */
  added: number
  total: number
}

export interface UploadOutcome {
  /** The files that went in, in order, even if the selection stopped. */
  refs: FileRef[]
  cancelled: boolean
  /** Set when a file couldn't be added. */
  stopped: UploadStop | null
}

/** Waits before sending a batch again after the connection dropped. Sending
 * one again is safe: files are stored by content, so one that already went
 * in is recognised, not stored twice. */
export const RETRY_DELAYS_MS = [2000]

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

/** Which file of `sizes` the `loaded`-th byte belongs to. */
function fileAt(sizes: number[], loaded: number): number {
  let end = 0
  for (let i = 0; i < sizes.length; i++) {
    end += sizes[i]
    if (loaded < end) return i
  }
  return Math.max(0, sizes.length - 1)
}

/** Adds files to civex a batch at a time (`fileBatches`: a few requests
 * however many files there are), reporting live progress and letting the
 * person stop. Nothing is lost when a selection stops: cancelling keeps what
 * had gone in, and a file that can't be added stops it with `stopped` saying
 * why and holding the rest, so the caller saves what went in and offers the
 * rest again (`UploadStopped`). */
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
      const size = files.reduce((n, f) => n + f.size, 0)
      const started = performance.now()
      let before = 0 // bytes of the batches already in

      function say(
        first: number,
        batch: File[],
        loaded: number,
        saving: boolean,
      ) {
        const done = before + loaded
        const seconds = (performance.now() - started) / 1000
        const rate = seconds > 0.25 ? done / seconds : 0
        const i =
          first +
          fileAt(
            batch.map((f) => f.size),
            loaded,
          )
        setCurrent({
          index: i,
          total: files.length,
          name: files[i].name,
          size,
          loaded: done,
          rate,
          eta: rate > 0 ? (size - done) / rate : null,
          saving,
        })
      }

      function stop(index: number, message: string): UploadOutcome {
        const stop: UploadStop = {
          name: files[index].name,
          message,
          rest: files.slice(index),
          added: refs.length,
          total: files.length,
        }
        setStopped(stop)
        return { refs, cancelled: false, stopped: stop }
      }

      try {
        for (const batch of fileBatches(files)) {
          const first = refs.length
          say(first, batch, 0, false)
          let result
          for (let attempt = 0; ; attempt++) {
            try {
              result = await filesApi.uploadBatch(
                batch,
                (info) => say(first, batch, info.loaded, info.saving),
                collectionId,
                abort.signal,
              )
              break
            } catch (err) {
              if (err instanceof DOMException && err.name === 'AbortError')
                throw err
              const again =
                err instanceof UploadConnectionError &&
                attempt < RETRY_DELAYS_MS.length
              if (!again)
                return stop(
                  first,
                  err instanceof Error ? err.message : String(err),
                )
              await wait(RETRY_DELAYS_MS[attempt], abort.signal)
            }
          }
          refs.push(...result.files)
          if (result.stopped)
            return stop(first + result.stopped.index, result.stopped.message)
          before += batch.reduce((n, f) => n + f.size, 0)
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
