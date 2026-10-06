import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import type { FileRef } from '../../api/files'
import { FileLink, FileLocationChip } from './FileLocation'
import { FieldValue } from './FieldValue'
import { RecordStorageSummary } from './RecordStorageSummary'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const SHA = 'ab'.repeat(32)

const file = (over: Partial<FileRef> = {}): FileRef => ({
  sha256: SHA,
  filename: 'scan.png',
  size: 2048,
  volume: 'default',
  location: { volume: 'archive', state: 'online', available: true },
  ...over,
})

const OFFLINE = {
  volume: 'archive',
  state: 'offline',
  available: false,
} as const

let advanced: boolean
let volumeCount: number
let calls: string[]

beforeEach(() => {
  advanced = false
  volumeCount = 1
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://x')
      calls.push(url.pathname)
      if (url.pathname === '/api/settings/ui')
        return json({ show_advanced: advanced })
      if (url.pathname === '/api/store/volumes')
        return json(
          Array.from({ length: volumeCount }, (_, i) => ({ name: `v${i}` })),
        )
      if (url.pathname === `/api/files/${SHA}/info`)
        return json({
          sha256: SHA,
          size: 2048,
          copies: [
            {
              volume: 'archive',
              path: `/media/archive/ab/${SHA.slice(2)}`,
              present: true,
              state: 'online',
              network: true,
            },
          ],
          records: 3,
          jobs: 0,
          collections: [{ id: 'c1', name: 'study', records: 3 }],
        })
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderIt(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

/** The settings and volumes queries have answered. */
const settled = () =>
  waitFor(() => {
    expect(calls).toContain('/api/settings/ui')
    expect(calls).toContain('/api/store/volumes')
  })

describe('FileLocationChip', () => {
  it('says nothing on a single-volume project when nothing is wrong', async () => {
    const { container } = renderIt(<FileLocationChip file={file()} />)
    await settled()

    expect(container).toBeEmptyDOMElement()
  })

  it('names the volume once there is a choice of volumes', async () => {
    volumeCount = 2
    renderIt(<FileLocationChip file={file()} />)

    expect(
      await screen.findByTitle(
        "Stored on 'archive' (Online). Click for details.",
      ),
    ).toHaveTextContent('archive')
  })

  it('always says when another device added a file not downloaded yet', async () => {
    renderIt(
      <FileLocationChip
        file={file({
          location: {
            volume: null,
            state: 'remote',
            available: null,
            reason: 'Not downloaded to this computer yet.',
            fix: 'Opening or exporting it downloads it from the server.',
          },
        })}
      />,
    )
    const chip = await screen.findByText('on the server')
    expect(chip.closest('button')).toHaveAttribute(
      'title',
      'Not downloaded to this computer yet: opening it downloads it.',
    )
  })

  it('always says when a file is on a volume that is not available', async () => {
    renderIt(<FileLocationChip file={file({ location: OFFLINE })} />)

    const chip = await screen.findByText('archive · offline')
    expect(chip.closest('button')).toHaveAttribute(
      'title',
      "On 'archive', which isn't available right now. Click to see what to do.",
    )
  })

  it('tells a person which drive to plug in, without leaving the record', async () => {
    const user = userEvent.setup()
    renderIt(
      <FileLocationChip
        file={file({
          location: {
            ...OFFLINE,
            reason: "'archive' isn't connected.",
            fix: "Plug in the drive for 'archive' and it will come back by itself.",
          },
        })}
      />,
    )

    await user.click(
      await screen.findByRole('button', { name: /archive · offline/ }),
    )

    const panel = await screen.findByRole('dialog', {
      name: 'Where this file is stored',
    })
    expect(within(panel).getByRole('alert')).toHaveTextContent(
      "It's on ‘archive’, which isn't available right now, so it can't be opened.",
    )
    expect(within(panel).getByText("'archive' isn't connected.")).toBeVisible()
    expect(
      within(panel).getByText(/Plug in the drive for 'archive'/),
    ).toBeVisible()
    expect(
      within(panel).getByRole('link', { name: /Open ‘archive’ in Settings/ }),
    ).toHaveAttribute('href', '/settings/storage/volumes/archive')
    // The technical detail stays out of the way until asked for.
    expect(calls).not.toContain(`/api/files/${SHA}/info`)
  })

  it('says in plain words where a healthy file is, and reveals details on request', async () => {
    volumeCount = 2
    const user = userEvent.setup()
    renderIt(<FileLocationChip file={file()} />)

    await user.click(
      await screen.findByRole('button', {
        name: 'Where scan.png is stored: archive',
      }),
    )

    const panel = await screen.findByRole('dialog', {
      name: 'Where this file is stored',
    })
    expect(within(panel).getByText('scan.png')).toBeInTheDocument()
    expect(within(panel).getByText('2.0 KB')).toBeInTheDocument()
    expect(panel).toHaveTextContent('Stored on archive · Online')
    expect(panel).toHaveTextContent('Ready to open.')
    expect(calls).not.toContain(`/api/files/${SHA}/info`) // nothing fetched yet

    await user.click(
      within(panel).getByRole('button', { name: 'More details' }),
    )

    expect(
      await within(panel).findByText(`/media/archive/ab/${SHA.slice(2)}`),
    ).toBeInTheDocument()
    expect(calls).toContain(`/api/files/${SHA}/info`)
    expect(
      within(panel).queryByRole('button', { name: 'More details' }),
    ).toBeNull()
  })

  it('has nothing to say, and fetches nothing, for a file with no location yet', async () => {
    const { container } = renderIt(
      <FileLocationChip file={file({ location: undefined })} />,
    )

    expect(container).toBeEmptyDOMElement()
    expect(calls).toEqual([])
  })

  it('shows an unknown location only in advanced mode', async () => {
    const unknown = file({
      location: { volume: null, state: 'unknown', available: null },
    })
    const { container } = renderIt(<FileLocationChip file={unknown} />)
    await settled()
    expect(container).toBeEmptyDOMElement()

    advanced = true
    renderIt(<FileLocationChip file={unknown} />)
    expect(await screen.findByText('location unknown')).toBeInTheDocument()
  })

  it('opens with the full details already showing in advanced mode, fetching them only then', async () => {
    advanced = true
    const user = userEvent.setup()
    renderIt(<FileLocationChip file={file()} />)

    const chip = await screen.findByRole('button', {
      name: 'Where scan.png is stored: archive',
    })
    expect(calls).not.toContain(`/api/files/${SHA}/info`)
    await user.click(chip)
    expect(
      screen.queryByRole('button', { name: 'More details' }),
    ).not.toBeInTheDocument()

    const panel = await screen.findByRole('dialog', {
      name: 'Where this file is stored',
    })
    expect(
      await within(panel).findByText(`/media/archive/ab/${SHA.slice(2)}`),
    ).toBeInTheDocument()
    expect(within(panel).getByText('Network')).toBeInTheDocument()
    expect(within(panel).getByText(SHA)).toBeInTheDocument()
    expect(within(panel).getByText('2.0 KB')).toBeInTheDocument()
    expect(within(panel).getByText('3 records')).toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: 'study' })).toHaveAttribute(
      'href',
      '/collections/c1',
    )
    expect(
      within(panel).getByRole('button', { name: 'Copy path on archive' }),
    ).toBeInTheDocument()
  })
})

describe('FileLink', () => {
  it('downloads under the resolved filename', () => {
    renderIt(
      <FileLink
        file={file({ resolved_filename: 'S01 scan.png' })}
        className="x"
      >
        Download
      </FileLink>,
    )

    const link = screen.getByRole('link', { name: 'Download' })
    expect(link).toHaveAttribute(
      'href',
      `/api/files/${SHA}?filename=${encodeURIComponent('S01 scan.png')}`,
    )
    expect(link).toHaveAttribute('download', 'S01 scan.png')
  })

  it('stops being a link when the file is on an unavailable volume', () => {
    renderIt(
      <FileLink
        file={file({ location: OFFLINE })}
        whenUnavailable={<span>Unavailable</span>}
      >
        Download
      </FileLink>,
    )

    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(
      screen.getByText('Unavailable').closest('span[aria-disabled]'),
    ).toBeTruthy()
  })
})

describe('FileLink download check', () => {
  it('says which drive to plug in when it vanished after the page loaded', async () => {
    const detail =
      "This file is on volume 'archive', which isn't available right now (not connected). Plug it in."
    const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
      String(input).startsWith(`/api/files/${SHA}?`)
        ? json({ detail }, 503)
        : json({}),
    )
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    renderIt(<FileLink file={file()}>Download</FileLink>)

    await user.click(screen.getByRole('link', { name: 'Download' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(detail)
  })

  it('starts the browser download and says so when the file can be served', async () => {
    const clicked = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {})
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('bytes', { status: 200 })),
    )
    const user = userEvent.setup()
    renderIt(<FileLink file={file()}>Download</FileLink>)

    await user.click(screen.getByRole('link', { name: 'Download' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      "Download started. It's in your browser's downloads.",
    )
    expect(clicked).toHaveBeenCalled()
    clicked.mockRestore()
  })

  it('leaves a modified click (open in a new tab) to the browser', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    renderIt(<FileLink file={file()}>Download</FileLink>)

    const user = userEvent.setup()
    await user.keyboard('{Control>}')
    await user.click(screen.getByRole('link', { name: 'Download' }))
    await user.keyboard('{/Control}')

    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('FieldValue with files', () => {
  it('shows an unavailable file as unavailable, with where it is', async () => {
    renderIt(<FieldValue value={file({ location: OFFLINE })} />)

    expect(await screen.findByText('archive · offline')).toBeInTheDocument()
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: 'Download' }),
    ).not.toBeInTheDocument()
  })

  it('keeps downloading an available file, in a list too', async () => {
    volumeCount = 2
    const second = file({
      sha256: 'cd'.repeat(32),
      filename: 'b.png',
      location: { volume: 'default', state: 'online', available: true },
    })
    renderIt(<FieldValue value={[file(), second]} />)

    expect(
      await screen.findAllByRole('link', { name: 'Download' }),
    ).toHaveLength(2)
    expect(
      await screen.findByTitle(
        "Stored on 'default' (Online). Click for details.",
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByTitle("Stored on 'archive' (Online). Click for details."),
    ).toBeInTheDocument()
  })
})

describe('RecordStorageSummary', () => {
  const data = (...files: FileRef[]) => ({ title: 'x', scans: files })

  it('is silent for a record with no files', async () => {
    const { container } = renderIt(
      <RecordStorageSummary data={{ title: 'x' }} />,
    )
    await waitFor(() => expect(calls).toContain('/api/settings/ui'))

    expect(container).toBeEmptyDOMElement()
  })

  it('is silent when all files are together and nothing is wrong', async () => {
    const { container } = renderIt(
      <RecordStorageSummary
        data={data(file(), file({ sha256: 'cd'.repeat(32) }))}
      />,
    )
    await waitFor(() => expect(calls).toContain('/api/settings/ui'))

    expect(container).toBeEmptyDOMElement()
  })

  it('says when a record is split across volumes', async () => {
    const other = file({
      sha256: 'cd'.repeat(32),
      location: { volume: 'default', state: 'online', available: true },
    })
    renderIt(
      <RecordStorageSummary
        data={data(file(), file({ sha256: 'ef'.repeat(32) }), other)}
      />,
    )

    const note = await screen.findByRole('group', {
      name: "Where this record's files are stored",
    })
    expect(note).toHaveTextContent('3 files stored on archive (2), default (1)')
    expect(note).toHaveTextContent('Split across 2 volumes')
    expect(
      within(note).getByRole('link', { name: 'Storage settings' }),
    ).toHaveAttribute('href', '/settings/storage')
  })

  it('flags files that cannot be opened right now', async () => {
    renderIt(<RecordStorageSummary data={data(file({ location: OFFLINE }))} />)

    expect(
      await screen.findByText('1 not available right now'),
    ).toBeInTheDocument()
  })

  it('always shows in advanced mode', async () => {
    advanced = true
    renderIt(<RecordStorageSummary data={data(file())} />)

    expect(
      await screen.findByText('1 file stored on archive (1)'),
    ).toBeInTheDocument()
  })
})
