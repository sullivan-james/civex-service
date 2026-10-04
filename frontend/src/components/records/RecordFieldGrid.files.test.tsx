import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { RecordFieldGrid } from './RecordFieldGrid'
import { filesApi } from '../../api/files'
import type { Field } from '../../api/schemas'

vi.mock('../../api/files', () => ({
  filesApi: { uploadStreaming: vi.fn() },
}))

const ref = (name: string, sha: string) => ({
  volume: 'default',
  sha256: sha,
  filename: name,
  size: 2048,
})

function fileField(type: 'file' | 'file_list', restrictions = {}): Field {
  return {
    id: 'f',
    name: 'clip',
    label: 'Clip',
    type,
    required: false,
    restrictions,
    default: null,
    position: 0,
  } as unknown as Field
}

function renderGrid(
  type: 'file' | 'file_list',
  data: Record<string, unknown>,
  restrictions = {},
) {
  const onSave = vi.fn()
  render(
    <MemoryRouter>
      <RecordFieldGrid
        fields={[fileField(type, restrictions)]}
        data={data}
        onSave={onSave}
      />
    </MemoryRouter>,
  )
  return onSave
}

function pick(name: string, mime = 'audio/wav', size = 1) {
  const input = screen.getByLabelText('Upload Clip') as HTMLInputElement
  // The picker's own `accept` filter is bypassed: a user can still drag a
  // non-matching file in, which is what the up-front check is for.
  return userEvent
    .setup({ applyAccept: false })
    .upload(input, new File([new Uint8Array(size)], name, { type: mime }))
}

const upload = vi.mocked(filesApi.uploadStreaming)

beforeEach(() => {
  upload.mockReset()
})

describe('attaching files to a record', () => {
  it('attaches as soon as the file is chosen, with nothing to approve', async () => {
    upload.mockResolvedValue(ref('a.wav', 'aa'))
    const onSave = renderGrid('file', {})

    await pick('a.wav')

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith('clip', ref('a.wav', 'aa')),
    )
    expect(screen.queryByText(/approval/i)).toBeNull()
    expect(screen.queryByRole('button', { name: /Approve/ })).toBeNull()
  })

  it('adds a batch to a file_list alongside what is already there', async () => {
    upload
      .mockResolvedValueOnce(ref('b.wav', 'bb'))
      .mockResolvedValueOnce(ref('c.wav', 'cc'))
    const onSave = renderGrid('file_list', { clip: [ref('a.wav', 'aa')] })

    await userEvent.upload(screen.getByLabelText('Upload Clip'), [
      new File(['x'], 'b.wav', { type: 'audio/wav' }),
      new File(['y'], 'c.wav', { type: 'audio/wav' }),
    ])

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith('clip', [
        ref('a.wav', 'aa'),
        ref('b.wav', 'bb'),
        ref('c.wav', 'cc'),
      ]),
    )
  })

  it('takes a file dropped onto the field', async () => {
    upload.mockResolvedValue(ref('dropped.wav', 'dd'))
    const onSave = renderGrid('file', {})
    const zone = screen.getByLabelText('Upload Clip').closest('label')!

    fireEvent.drop(zone, {
      dataTransfer: {
        files: [new File(['x'], 'dropped.wav', { type: 'audio/wav' })],
      },
    })

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith('clip', ref('dropped.wav', 'dd')),
    )
  })

  it('refuses a file the field does not accept, before uploading anything', async () => {
    const onSave = renderGrid('file', {}, { accept: 'audio/*' })

    await pick('notes.pdf', 'application/pdf')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'notes.pdf: Type not accepted here (accepted: audio/*)',
    )
    expect(upload).not.toHaveBeenCalled()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('refuses a file over the size limit, before uploading anything', async () => {
    const onSave = renderGrid('file', {}, { max_size: 10 })

    await pick('big.wav', 'audio/wav', 100)

    expect(await screen.findByRole('alert')).toHaveTextContent(/Too large/)
    expect(upload).not.toHaveBeenCalled()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('shows what went wrong when the upload fails, and saves nothing', async () => {
    upload.mockRejectedValue(new Error('No space left on the drive'))
    const onSave = renderGrid('file', {})

    await pick('a.wav')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'No space left on the drive',
    )
    expect(onSave).not.toHaveBeenCalled()
  })
})

describe('removing and replacing files', () => {
  it('asks before removing a file, and keeps it if you say no', async () => {
    const user = userEvent.setup()
    const onSave = renderGrid('file', { clip: ref('a.wav', 'aa') })

    await user.click(screen.getByRole('button', { name: 'Remove a.wav' }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/from this record/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(onSave).not.toHaveBeenCalled()
  })

  it('removes the file once confirmed', async () => {
    const user = userEvent.setup()
    const onSave = renderGrid('file', { clip: ref('a.wav', 'aa') })

    await user.click(screen.getByRole('button', { name: 'Remove a.wav' }))
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', {
        name: 'Remove file',
      }),
    )

    expect(onSave).toHaveBeenCalledWith('clip', undefined)
  })

  it('removes one file from a list, leaving the others', async () => {
    const user = userEvent.setup()
    const onSave = renderGrid('file_list', {
      clip: [ref('a.wav', 'aa'), ref('b.wav', 'bb')],
    })

    await user.click(screen.getByRole('button', { name: 'Remove a.wav' }))
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', {
        name: 'Remove file',
      }),
    )

    expect(onSave).toHaveBeenCalledWith('clip', [ref('b.wav', 'bb')])
  })

  it('asks before replacing a file, since that removes the current one', async () => {
    upload.mockResolvedValue(ref('new.wav', 'nn'))
    const user = userEvent.setup()
    const onSave = renderGrid('file', { clip: ref('old.wav', 'oo') })

    await pick('new.wav')

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('old.wav')
    expect(dialog).toHaveTextContent('new.wav')
    expect(upload).not.toHaveBeenCalled() // nothing uploaded until you agree
    await user.click(
      within(dialog).getByRole('button', { name: 'Replace file' }),
    )

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith('clip', ref('new.wav', 'nn')),
    )
  })

  it('leaves the current file alone if you decline to replace it', async () => {
    const user = userEvent.setup()
    const onSave = renderGrid('file', { clip: ref('old.wav', 'oo') })

    await pick('new.wav')
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', {
        name: 'Cancel',
      }),
    )

    expect(upload).not.toHaveBeenCalled()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('adds to a list without asking, because nothing is removed', async () => {
    upload.mockResolvedValue(ref('b.wav', 'bb'))
    const onSave = renderGrid('file_list', { clip: [ref('a.wav', 'aa')] })

    await pick('b.wav')

    await waitFor(() => expect(onSave).toHaveBeenCalled())
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('upload progress', () => {
  it('shows live progress while uploading, and the server saving at the end', async () => {
    let report!: Parameters<typeof filesApi.uploadStreaming>[1]
    let finish!: (r: ReturnType<typeof ref>) => void
    upload.mockImplementation(
      (_file, onProgress) =>
        new Promise((resolve) => {
          report = onProgress
          finish = resolve as typeof finish
        }),
    )
    const onSave = renderGrid('file', {})

    await pick('big.wav')
    expect(await screen.findByText('big.wav')).toBeInTheDocument()
    expect(screen.getByLabelText('Upload Clip')).toBeDisabled()

    report?.(0.5, { loaded: 512, total: 1024, saving: false })
    expect(await screen.findByText(/50%/)).toBeInTheDocument()

    report?.(1, { loaded: 1024, total: 1024, saving: true })
    expect(
      await screen.findByText('Sent. Saving to storage…'),
    ).toBeInTheDocument()

    finish(ref('big.wav', 'bb'))
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith('clip', ref('big.wav', 'bb')),
    )
    expect(screen.queryByRole('progressbar', { name: /Uploading/ })).toBeNull()
  })

  it('cancelling an upload stops it and saves nothing', async () => {
    upload.mockImplementation(
      (_file, _progress, _collection, signal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener('abort', () =>
            reject(new DOMException('cancelled', 'AbortError')),
          )
        }),
    )
    const onSave = renderGrid('file', {})

    await pick('big.wav')
    await userEvent.click(
      await screen.findByRole('button', { name: 'Cancel upload' }),
    )

    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: 'Cancel upload' }),
      ).toBeNull(),
    )
    expect(screen.queryByRole('alert')).toBeNull() // not an error: you chose it
    expect(screen.getByLabelText('Upload Clip')).toBeEnabled()
    expect(onSave).not.toHaveBeenCalled()
  })
})
