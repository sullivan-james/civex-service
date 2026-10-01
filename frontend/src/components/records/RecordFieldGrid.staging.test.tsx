import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

function pick(name: string, mime = 'audio/wav') {
  const input = screen.getByLabelText('Upload Clip') as HTMLInputElement
  // The picker's own `accept` filter is bypassed: a user can still drag a
  // non-matching file in, which is what the staged check is for.
  return userEvent
    .setup({ applyAccept: false })
    .upload(input, new File(['x'], name, { type: mime }))
}

beforeEach(() => {
  vi.mocked(filesApi.uploadStreaming).mockReset()
})

describe('staged file uploads', () => {
  it('holds an upload until it is approved', async () => {
    vi.mocked(filesApi.uploadStreaming).mockResolvedValue(ref('a.wav', 'aa'))
    const onSave = vi.fn()
    render(
      <RecordFieldGrid
        fields={[fileField('file')]}
        data={{}}
        onSave={onSave}
      />,
    )

    await pick('a.wav')
    expect(await screen.findByText(/Waiting for approval/)).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    expect(onSave).toHaveBeenCalledWith('clip', ref('a.wav', 'aa'))
    expect(screen.queryByText(/Waiting for approval/)).toBeNull()
  })

  it('discarding saves nothing', async () => {
    vi.mocked(filesApi.uploadStreaming).mockResolvedValue(ref('a.wav', 'aa'))
    const onSave = vi.fn()
    render(
      <RecordFieldGrid
        fields={[fileField('file')]}
        data={{}}
        onSave={onSave}
      />,
    )

    await pick('a.wav')
    await userEvent.click(
      await screen.findByRole('button', { name: 'Discard' }),
    )
    expect(onSave).not.toHaveBeenCalled()
    expect(screen.queryByText(/Waiting for approval/)).toBeNull()
  })

  it('blocks approval of a file the field does not accept', async () => {
    vi.mocked(filesApi.uploadStreaming).mockResolvedValue(
      ref('notes.pdf', 'bb'),
    )
    const onSave = vi.fn()
    render(
      <RecordFieldGrid
        fields={[fileField('file', { accept: 'audio/*' })]}
        data={{}}
        onSave={onSave}
      />,
    )
    await pick('notes.pdf', 'application/pdf')
    expect(await screen.findByText(/Type not accepted/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
  })

  it('approves a batch into a file_list alongside what is already there', async () => {
    vi.mocked(filesApi.uploadStreaming)
      .mockResolvedValueOnce(ref('b.wav', 'bb'))
      .mockResolvedValueOnce(ref('c.wav', 'cc'))
    const onSave = vi.fn()
    render(
      <RecordFieldGrid
        fields={[fileField('file_list')]}
        data={{ clip: [ref('a.wav', 'aa')] }}
        onSave={onSave}
      />,
    )
    const input = screen.getByLabelText('Upload Clip') as HTMLInputElement
    await userEvent.upload(input, [
      new File(['x'], 'b.wav', { type: 'audio/wav' }),
      new File(['y'], 'c.wav', { type: 'audio/wav' }),
    ])
    await userEvent.click(
      await screen.findByRole('button', { name: 'Approve 2 files' }),
    )
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith('clip', [
        ref('a.wav', 'aa'),
        ref('b.wav', 'bb'),
        ref('c.wav', 'cc'),
      ]),
    )
  })
})
