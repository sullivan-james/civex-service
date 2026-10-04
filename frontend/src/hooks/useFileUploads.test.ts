import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { filesApi, type FileRef, type UploadInfo } from '../api/files'
import { useFileUploads } from './useFileUploads'

vi.mock('../api/files', () => ({ filesApi: { uploadStreaming: vi.fn() } }))

const ref = (name: string): FileRef => ({
  sha256: name.padEnd(64, '0'),
  filename: name,
  size: 100,
  volume: 'default',
})
const file = (name: string, size = 100) =>
  new File([new Uint8Array(size)], name)

const upload = vi.mocked(filesApi.uploadStreaming)

beforeEach(() => {
  upload.mockReset()
})

describe('useFileUploads', () => {
  it('reports which file, how far, and that the server is saving at the end', async () => {
    let report!: (f: number, i?: UploadInfo) => void
    let finish!: (r: FileRef) => void
    upload.mockImplementation(
      (_file, onProgress) =>
        new Promise<FileRef>((resolve) => {
          report = onProgress!
          finish = resolve
        }),
    )
    const { result } = renderHook(() => useFileUploads('c1'))

    let done!: Promise<unknown>
    act(() => {
      done = result.current.run([file('a.wav', 1000)])
    })
    await waitFor(() => expect(result.current.current?.name).toBe('a.wav'))
    expect(result.current.uploading).toBe(true)
    expect(upload.mock.calls[0][2]).toBe('c1') // steered to the collection's home

    act(() => report(0.5, { loaded: 500, total: 1000, saving: false }))
    expect(result.current.current).toMatchObject({
      loaded: 500,
      size: 1000,
      saving: false,
      total: 1,
      index: 0,
    })

    act(() => report(1, { loaded: 1000, total: 1000, saving: true }))
    expect(result.current.current?.saving).toBe(true)

    await act(async () => {
      finish(ref('a.wav'))
      await done
    })
    expect(result.current.current).toBeNull()
    expect(result.current.uploading).toBe(false)
  })

  it('uploads a batch in order and numbers it', async () => {
    upload.mockImplementation(async (f) => ref(f.name))
    const { result } = renderHook(() => useFileUploads())

    let outcome!: Awaited<ReturnType<typeof result.current.run>>
    await act(async () => {
      outcome = await result.current.run([file('a'), file('b'), file('c')])
    })

    expect(outcome.cancelled).toBe(false)
    expect(outcome.refs.map((r) => r.filename)).toEqual(['a', 'b', 'c'])
    expect(upload).toHaveBeenCalledTimes(3)
  })

  it('keeps what finished when cancelled part-way', async () => {
    upload.mockImplementationOnce(async (f) => ref(f.name))
    upload.mockImplementationOnce(
      (_f, _p, _c, signal) =>
        new Promise<FileRef>((_resolve, reject) => {
          signal!.addEventListener('abort', () =>
            reject(new DOMException('cancelled', 'AbortError')),
          )
        }),
    )
    const { result } = renderHook(() => useFileUploads())

    let outcome!: Awaited<ReturnType<typeof result.current.run>>
    let done!: Promise<void>
    act(() => {
      done = result.current.run([file('a'), file('b'), file('c')]).then((o) => {
        outcome = o
      })
    })
    await waitFor(() => expect(result.current.current?.name).toBe('b'))

    act(() => result.current.cancel())
    await act(async () => {
      await done
    })

    expect(outcome.cancelled).toBe(true)
    expect(outcome.refs.map((r) => r.filename)).toEqual(['a'])
    expect(upload).toHaveBeenCalledTimes(2) // 'c' was never started
    expect(result.current.current).toBeNull()
  })

  it('throws any other failure for the caller to show', async () => {
    upload.mockRejectedValue(new Error('No space left'))
    const { result } = renderHook(() => useFileUploads())

    await expect(
      act(async () => {
        await result.current.run([file('a')])
      }),
    ).rejects.toThrow('No space left')
    expect(result.current.current).toBeNull()
  })
})
