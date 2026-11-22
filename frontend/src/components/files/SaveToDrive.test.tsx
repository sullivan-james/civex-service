import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ToastProvider } from '../ui/ToastProvider'
import { SaveToDriveDialog } from './SaveToDrive'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  })

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname === '/api/store/volumes')
        return json([
          {
            name: 'archive',
            available: true,
            state: 'online',
            disk_free_bytes: 5_000_000,
          },
        ])
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function show(
  onSave = vi.fn(async () => ({ path: '/mnt/archive/_exports/v1.zip' })),
) {
  const onDownload = vi.fn()
  const onClose = vi.fn()
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ToastProvider>
        <SaveToDriveDialog
          title="Save a copy"
          need={1000}
          onSave={onSave}
          onDownload={onDownload}
          onClose={onClose}
        />
      </ToastProvider>
    </QueryClientProvider>,
  )
  return { onSave, onDownload, onClose }
}

describe('saving a copy', () => {
  it('goes onto a drive of this computer by default, and says where', async () => {
    const user = userEvent.setup()
    const { onSave, onDownload, onClose } = show()
    await user.selectOptions(
      await screen.findByLabelText('Drive'),
      await screen.findByRole('option', { name: /archive/ }),
    )
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledWith('archive'))
    expect(onDownload).not.toHaveBeenCalled()
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(
      await screen.findByText('Saved: /mnt/archive/_exports/v1.zip'),
    ).toBeInTheDocument()
  })

  it('can still be downloaded through the browser', async () => {
    const user = userEvent.setup()
    const { onSave, onDownload } = show()
    await user.click(screen.getByRole('radio', { name: 'Download' }))
    expect(screen.queryByLabelText('Drive')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Download' }))
    expect(onDownload).toHaveBeenCalled()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('says why when the drive refuses it, and stays open', async () => {
    const user = userEvent.setup()
    const { onClose } = show(
      vi.fn(async () => {
        throw new Error("'archive' can't be written to now")
      }),
    )
    await user.click(await screen.findByRole('button', { name: 'Save' }))
    expect(
      await screen.findByText(/can't be written to now/),
    ).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })
})
