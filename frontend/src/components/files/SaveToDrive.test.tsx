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
  localStorage.clear()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://x')
      // The app's own folder browser: any folder of this computer.
      if (url.pathname === '/api/store/browse')
        return json({
          path: '/media/usb',
          parent: '/media',
          entries: [],
          places: [],
          truncated: false,
        })
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function show(
  onSave = vi.fn(async () => ({ path: '/media/usb/v1.civex.zip' })),
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
          title="Copy to another project"
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
  it('needs a folder first, chosen with the folder browser, and remembers it', async () => {
    const user = userEvent.setup()
    show()
    expect(screen.getByText('No folder chosen')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Choose…' }))
    expect(
      await screen.findByRole('heading', { name: 'Choose a folder' }),
    ).toBeInTheDocument()
  })

  it('saves into the folder in the background, and says where', async () => {
    // A folder used before is offered again.
    localStorage.setItem('save.folder', JSON.stringify('/media/usb'))
    const user = userEvent.setup()
    const { onSave, onDownload, onClose } = show()
    expect(screen.getByText('/media/usb')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith('/media/usb', expect.any(String)),
    )
    expect(onDownload).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
    expect(
      await screen.findByText('Saved: /media/usb/v1.civex.zip'),
    ).toBeInTheDocument()
  })

  it('can still be downloaded through the browser', async () => {
    const user = userEvent.setup()
    const { onSave, onDownload } = show()
    await user.click(screen.getByRole('radio', { name: 'Download' }))
    expect(screen.queryByRole('button', { name: 'Choose…' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Download' }))
    expect(onDownload).toHaveBeenCalled()
    expect(onSave).not.toHaveBeenCalled()
  })
})
