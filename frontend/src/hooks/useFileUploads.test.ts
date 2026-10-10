import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import {
  BATCH_FILES,
  fileBatches,
  filesApi,
  UploadConnectionError,
  type BatchResult,
  type FileRef,
  type UploadInfo,
} from '../api/files'
import { useFileUploads } from './useFileUploads'

vi.mock('../api/files', async (original) => ({
  ...(await original<typeof import('../api/files')>()),
  filesApi: { uploadBatch: vi.fn() },
}))

const ref = (name: string): FileRef => ({
  sha256: name.padEnd(64, '0'),
  filename: name,
  size: 100,
  volume: 'default',
})
const file = (name: string, size = 100) =>
  new File([new Uint8Array(size)], name)
const all = async (files: File[]): Promise<BatchResult> => ({
  files: files.map((f) => ref(f.name)),
  stopped: null,
})

const send = vi.mocked(filesApi.uploadBatch)

beforeEach(() => {
  send.mockReset()
})

describe('fileBatches', () => {
  it('splits by count and by bytes, keeping order, a big file alone', () => {
    const sizes = (n: number[]) => n.map((size) => ({ size }))
    expect(fileBatches(sizes([1, 1, 1, 1, 1]), 2, 100)).toEqual([
      sizes([1, 1]),
      sizes([1, 1]),
      sizes([1]),
    ])
    expect(fileBatches(sizes([60, 60, 500, 10]), 10, 100)).toEqual([
      sizes([60]),
      sizes([60]),
      sizes([500]),
      sizes([10]),
    ])
  })
})

describe('useFileUploads', () => {
  it('reports which file, how far the selection is, and saving at the end', async () => {
    let report!: (i: UploadInfo) => void
    let finish!: (r: BatchResult) => void
    send.mockImplementation(
      (_files, onProgress) =>
        new Promise<BatchResult>((resolve) => {
          report = onProgress!
          finish = resolve
        }),
    )
    const { result } = renderHook(() => useFileUploads('c1'))

    let done!: Promise<unknown>
    act(() => {
      done = result.current.run([file('a.wav', 1000), file('b.wav', 1000)])
    })
    await waitFor(() => expect(result.current.current?.name).toBe('a.wav'))
    expect(result.current.uploading).toBe(true)
    expect(send.mock.calls[0][2]).toBe('c1') // steered to the collection's home

    act(() => report({ loaded: 1500, total: 2000, saving: false }))
    expect(result.current.current).toMatchObject({
      name: 'b.wav',
      index: 1,
      total: 2,
      loaded: 1500,
      size: 2000,
      saving: false,
    })

    act(() => report({ loaded: 2000, total: 2000, saving: true }))
    expect(result.current.current?.saving).toBe(true)

    await act(async () => {
      finish({ files: [ref('a.wav'), ref('b.wav')], stopped: null })
      await done
    })
    expect(result.current.current).toBeNull()
    expect(result.current.uploading).toBe(false)
  })

  it('sends many files in a few requests, in order', async () => {
    send.mockImplementation(all)
    const { result } = renderHook(() => useFileUploads())
    const files = Array.from({ length: BATCH_FILES * 2 + 1 }, (_, i) =>
      file(`f${i}`),
    )

    let outcome!: Awaited<ReturnType<typeof result.current.run>>
    await act(async () => {
      outcome = await result.current.run(files)
    })

    expect(send).toHaveBeenCalledTimes(3)
    expect(outcome.cancelled).toBe(false)
    expect(outcome.stopped).toBeNull()
    expect(outcome.refs.map((r) => r.filename)).toEqual(
      files.map((f) => f.name),
    )
  })

  it('keeps what went in when cancelled part-way', async () => {
    send.mockImplementationOnce(all)
    send.mockImplementationOnce(
      (_f, _p, _c, signal) =>
        new Promise<BatchResult>((_resolve, reject) => {
          signal!.addEventListener('abort', () =>
            reject(new DOMException('cancelled', 'AbortError')),
          )
        }),
    )
    const { result } = renderHook(() => useFileUploads())
    const files = Array.from({ length: BATCH_FILES + 1 }, (_, i) =>
      file(`f${i}`),
    )

    let outcome!: Awaited<ReturnType<typeof result.current.run>>
    let done!: Promise<void>
    act(() => {
      done = result.current.run(files).then((o) => {
        outcome = o
      })
    })
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2))

    act(() => result.current.cancel())
    await act(async () => {
      await done
    })

    expect(outcome.cancelled).toBe(true)
    expect(outcome.refs).toHaveLength(BATCH_FILES)
    expect(result.current.current).toBeNull()
  })

  it('stops at a file civex could not store, keeping what went in and the rest', async () => {
    send.mockResolvedValueOnce({
      files: [ref('a')],
      stopped: { index: 1, message: 'No space left' },
    })
    const { result } = renderHook(() => useFileUploads())

    let outcome!: Awaited<ReturnType<typeof result.current.run>>
    await act(async () => {
      outcome = await result.current.run([file('a'), file('b'), file('c')])
    })

    expect(outcome.refs.map((r) => r.filename)).toEqual(['a'])
    expect(outcome.stopped).toMatchObject({
      name: 'b',
      message: 'No space left',
      added: 1,
      total: 3,
    })
    expect(outcome.stopped?.rest.map((f) => f.name)).toEqual(['b', 'c'])
    expect(result.current.stopped?.name).toBe('b')
    expect(send).toHaveBeenCalledTimes(1) // a refusal isn't sent again
  })

  it('sends a batch again when the connection dropped', async () => {
    vi.useFakeTimers()
    try {
      send
        .mockRejectedValueOnce(new UploadConnectionError('dropped'))
        .mockImplementationOnce(all)
      const { result } = renderHook(() => useFileUploads())

      let outcome!: Awaited<ReturnType<typeof result.current.run>>
      await act(async () => {
        const running = result.current.run([file('a')])
        await vi.advanceTimersByTimeAsync(2000)
        outcome = await running
      })

      expect(outcome.refs.map((r) => r.filename)).toEqual(['a'])
      expect(outcome.stopped).toBeNull()
      expect(send).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })
})
