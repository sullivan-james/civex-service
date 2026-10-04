import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FileDropZone } from './FileDropZone'

const file = (name: string) => new File(['x'], name)

describe('FileDropZone', () => {
  it('reports the files chosen with the picker', async () => {
    const onFiles = vi.fn()
    render(<FileDropZone inputLabel="Pick" multiple onFiles={onFiles} />)

    await userEvent.upload(screen.getByLabelText('Pick'), [
      file('a.txt'),
      file('b.txt'),
    ])

    expect(onFiles).toHaveBeenCalledOnce()
    expect(onFiles.mock.calls[0][0].map((f: File) => f.name)).toEqual([
      'a.txt',
      'b.txt',
    ])
  })

  it('reports files dropped onto it', () => {
    const onFiles = vi.fn()
    render(<FileDropZone inputLabel="Pick" multiple onFiles={onFiles} />)

    fireEvent.drop(screen.getByLabelText('Pick').closest('label')!, {
      dataTransfer: { files: [file('a.txt'), file('b.txt')] },
    })

    expect(onFiles.mock.calls[0][0]).toHaveLength(2)
  })

  it('takes only the first file when it holds one', () => {
    const onFiles = vi.fn()
    render(<FileDropZone inputLabel="Pick" onFiles={onFiles} />)

    fireEvent.drop(screen.getByLabelText('Pick').closest('label')!, {
      dataTransfer: { files: [file('a.txt'), file('b.txt')] },
    })

    expect(onFiles.mock.calls[0][0].map((f: File) => f.name)).toEqual(['a.txt'])
  })

  it('ignores a drop while disabled', () => {
    const onFiles = vi.fn()
    render(<FileDropZone inputLabel="Pick" disabled onFiles={onFiles} />)

    fireEvent.drop(screen.getByLabelText('Pick').closest('label')!, {
      dataTransfer: { files: [file('a.txt')] },
    })

    expect(onFiles).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Pick')).toBeDisabled()
  })

  it('says what to do, or what you gave it', () => {
    const { rerender } = render(<FileDropZone onFiles={() => {}} />)
    expect(screen.getByText(/Drop a file here or/)).toBeInTheDocument()

    rerender(<FileDropZone multiple onFiles={() => {}} />)
    expect(screen.getByText(/Drop files here or/)).toBeInTheDocument()

    rerender(
      <FileDropZone onFiles={() => {}}>
        <span>2 files chosen</span>
      </FileDropZone>,
    )
    expect(screen.getByText('2 files chosen')).toBeInTheDocument()
  })

  it('lets a label elsewhere name the file input', () => {
    render(
      <>
        <label htmlFor="clip">Clip</label>
        <FileDropZone id="clip" onFiles={() => {}} />
      </>,
    )
    expect(screen.getByLabelText('Clip')).toHaveAttribute('type', 'file')
  })
})
