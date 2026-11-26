import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import type { FileRef } from '../../api/files'
import { FileLocationChip } from './FileLocation'
import { UnreachableList } from '../files/UnreachableList'
import { ToDownloadNotice } from '../files/ToDownloadNotice'
import { RecordStorageSummary } from './RecordStorageSummary'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

const SHA = 'cd'.repeat(32)
let features: string[]

const file = (location: FileRef['location']): FileRef => ({
  sha256: SHA,
  filename: 'scan.png',
  size: 1,
  volume: '',
  location,
})

function renderIt(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
  // Until the server has said what it does, a local project is assumed.
  const featuresLoaded = () =>
    waitFor(() => expect(client.getQueryData(['features'])).toBeTruthy())
  return { ...view, featuresLoaded }
}

beforeEach(() => {
  features = ['accounts']
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const p = new URL(String(input), 'http://x').pathname
      if (p === '/api/status/features') return json({ features, all: {} })
      if (p === '/api/settings/ui') return json({ show_advanced: true })
      if (p === '/api/store/volumes')
        return json([{ name: 'a' }, { name: 'b' }])
      if (p === '/api/file-access/files')
        return json({
          items: [],
          total: 0,
          summary: [
            {
              place: 'missing',
              kind: 'missing',
              files: 2,
              bytes: 0,
              reason: '',
              fix: '',
            },
            {
              place: 'arriving',
              kind: 'arriving',
              files: 3,
              bytes: 0,
              reason: '',
              fix: '',
            },
            {
              place: 'vault',
              kind: 'unreachable',
              files: 1,
              bytes: 0,
              reason: '',
              fix: '',
            },
          ],
        })
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

describe('files on a host (accounts, no drives)', () => {
  it('says a file past the wait is missing, naming the device', async () => {
    renderIt(
      <FileLocationChip
        file={file({
          volume: null,
          state: 'absent',
          available: false,
          reason: "It isn't on this computer. It was added on 'laptop'.",
        })}
      />,
    )
    await screen.findByTitle(
      'Missing. It was added on ‘laptop’ and never uploaded.',
    )
    expect(
      screen.getByTitle(
        'Missing. It was added on ‘laptop’ and never uploaded.',
      ),
    ).toBeTruthy()
  })

  it('says an unreachable file is temporarily unavailable, never naming a drive', async () => {
    renderIt(
      <FileLocationChip
        file={file({ volume: 'vault', state: 'offline', available: false })}
      />,
    )
    await screen.findByText('temporarily unavailable')
    expect(
      screen.getByTitle('Temporarily unavailable. Try again shortly.'),
    ).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/vault/)
  })

  it('shows nothing for a file that is there, even in advanced mode', async () => {
    const { container, featuresLoaded } = renderIt(
      <FileLocationChip
        file={file({ volume: 'vault', state: 'online', available: true })}
      />,
    )
    await featuresLoaded()
    expect(container.textContent).toBe('')
  })

  it('lists unreachable groups without drive names', async () => {
    renderIt(
      <UnreachableList
        groups={[
          {
            volume: 'vault',
            state: 'offline',
            reason: 'r',
            fix: 'Plug it in',
            files: 2,
            bytes: 0,
            records: [],
          },
          {
            volume: null,
            state: 'absent',
            reason: '',
            fix: '',
            files: 1,
            bytes: 0,
            records: [],
          } as never,
        ]}
      />,
    )
    await screen.findByText('Temporarily unavailable. Try again shortly.')
    expect(screen.getByText(/Missing\./)).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/vault|Plug it in|drive/i)
  })

  it('says a file still arriving is not on the hub yet', async () => {
    renderIt(
      <FileLocationChip
        file={file({
          volume: null,
          state: 'arriving',
          available: null,
          reason: 'Uploading: the computer that added it is still sending it.',
        })}
      />,
    )
    await screen.findByText('not on the hub yet')
  })

  it('does not say files are downloaded to this computer', async () => {
    const { container, featuresLoaded } = renderIt(
      <ToDownloadNotice toFetch={{ files: 3, bytes: 10 }} />,
    )
    await featuresLoaded()
    await waitFor(() => expect(container.textContent).toBe(''))
  })

  it('summarises a record as hub status, with no way to change a drive', async () => {
    renderIt(<RecordStorageSummary recordId="r1" name="R" filesHref="/f" />)
    await screen.findByText(/3 files are not on the hub yet/)
    expect(screen.getByText(/2 files are missing/)).toBeTruthy()
    expect(screen.getByText(/1 file is temporarily unavailable/)).toBeTruthy()
    expect(screen.queryByText(/drive/i)).toBeNull()
  })
})

describe('files on a local project', () => {
  it('keeps the drive wording', async () => {
    features = ['volumes']
    renderIt(
      <FileLocationChip
        file={file({ volume: 'vault', state: 'offline', available: false })}
      />,
    )
    expect(await screen.findByText('vault · offline')).toBeTruthy()
  })
})
