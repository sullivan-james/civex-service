import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { UploadProgressState } from '../../hooks/useFileUploads'
import { UploadProgress } from './UploadProgress'

const state = (
  over: Partial<UploadProgressState> = {},
): UploadProgressState => ({
  index: 0,
  total: 1,
  name: 'big.wav',
  size: 10 * 1024 * 1024,
  loaded: 4 * 1024 * 1024,
  rate: 2 * 1024 * 1024,
  eta: 3,
  saving: false,
  ...over,
})

describe('UploadProgress', () => {
  it('shows share, bytes, speed and time left', () => {
    render(<UploadProgress state={state()} onCancel={() => {}} />)

    expect(screen.getByText('big.wav')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute(
      'aria-valuenow',
      '40',
    )
    const text = screen.getByRole('status').textContent
    expect(text).toContain('40%')
    expect(text).toContain('4.0 MB of 10.0 MB')
    expect(text).toContain('2.0 MB/s')
    expect(text).toContain('left')
  })

  it('numbers the files of a batch', () => {
    render(
      <UploadProgress
        state={state({ index: 1, total: 3 })}
        onCancel={() => {}}
      />,
    )
    expect(screen.getByText(/File 2 of 3:/)).toBeInTheDocument()
  })

  it('says the server is saving once every byte is sent, instead of sitting at 100%', () => {
    render(
      <UploadProgress
        state={state({ loaded: 10 * 1024 * 1024, saving: true })}
        onCancel={() => {}}
      />,
    )
    expect(screen.getByText('Sent. Saving to storage…')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow')
  })

  it('leaves out speed and time left until there is a reading', () => {
    render(
      <UploadProgress
        state={state({ loaded: 0, rate: 0, eta: null })}
        onCancel={() => {}}
      />,
    )
    const text = screen.getByRole('status').textContent
    expect(text).not.toContain('/s')
    expect(text).not.toContain('left')
  })

  it('can be cancelled', async () => {
    const onCancel = vi.fn()
    render(<UploadProgress state={state()} onCancel={onCancel} />)

    await userEvent.click(screen.getByRole('button', { name: 'Cancel upload' }))

    expect(onCancel).toHaveBeenCalledOnce()
  })
})
