import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AddVolumeModal } from './AddVolumeModal'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const inspection = (path: string, over: Record<string, unknown> = {}) => ({
  path,
  exists: true,
  is_dir: true,
  writable: true,
  will_create: false,
  inside_project: false,
  same_disk_as_project: false,
  free_bytes: 500 * 1024 ** 3,
  total_bytes: 2 * 1024 ** 4,
  existing_volume: null,
  marker_volume: null,
  has_civex_data: false,
  is_network: false,
  problems: [],
  warnings: [],
  ...over,
})

let inspections: Record<string, ReturnType<typeof inspection>>
let calls: { method: string; path: string; body?: unknown }[]
let addResponse: () => Response

beforeEach(() => {
  inspections = {}
  calls = []
  addResponse = () => json({ name: 'x' }, 201)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      calls.push({
        method,
        path: url.pathname,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      if (url.pathname === '/api/store/inspect') {
        const path = url.searchParams.get('path') ?? ''
        return json(inspections[path] ?? inspection(path))
      }
      if (url.pathname === '/api/store/volumes' && method === 'POST')
        return addResponse()
      if (url.pathname === '/api/store/browse')
        return json({
          path: '/media/usb',
          parent: '/media',
          entries: [{ name: 'civex', path: '/media/usb/civex' }],
          truncated: false,
          locations: [],
          hint: null,
        })
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderIt(existingNames: string[] = ['default']) {
  const onClose = vi.fn()
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <AddVolumeModal existingNames={existingNames} onClose={onClose} />
    </QueryClientProvider>,
  )
  return { onClose }
}

const addButton = () => screen.getByRole('button', { name: 'Add volume' })

async function fill(user: ReturnType<typeof userEvent.setup>, path: string) {
  await user.type(screen.getByLabelText(/volume name/i), 'archive')
  await user.type(screen.getByLabelText(/^folder/i), path)
}

describe('AddVolumeModal', () => {
  it('is organised into steps and starts with nothing to add', () => {
    renderIt()

    expect(screen.getByRole('heading', { name: 'Name' })).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Location' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'How it is used' }),
    ).toBeInTheDocument()
    expect(addButton()).toBeDisabled()
  })

  it('checks the folder as you type and enables adding when it is fine', async () => {
    const user = userEvent.setup()
    renderIt()

    await fill(user, '/media/usb/civex')

    const check = await screen.findByLabelText('Location check', undefined, {
      timeout: 3000,
    })
    expect(check).toHaveTextContent('Separate drive')
    expect(check).toHaveTextContent('Existing folder')
    expect(check).toHaveTextContent('500 GB free of 2.0 TB')
    expect(check).toHaveTextContent('Ready to add')
    await waitFor(() => expect(addButton()).toBeEnabled())
  })

  it('shows problems and blocks adding', async () => {
    inspections['/media/usb'] = inspection('/media/usb', {
      problems: ["That folder is already the volume 'usb'."],
    })
    const user = userEvent.setup()
    renderIt()

    await fill(user, '/media/usb')

    expect(
      await screen.findByText(
        "That folder is already the volume 'usb'.",
        undefined,
        {
          timeout: 3000,
        },
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText('Ready to add')).not.toBeInTheDocument()
    expect(addButton()).toBeDisabled()
  })

  it('marks a network drive and shows its warnings without blocking', async () => {
    inspections['/mnt/nas/civex'] = inspection('/mnt/nas/civex', {
      is_network: true,
      same_disk_as_project: false,
      warnings: ['This is a network location. It can be slow.'],
    })
    const user = userEvent.setup()
    renderIt()

    await fill(user, '/mnt/nas/civex')

    const check = await screen.findByLabelText('Location check', undefined, {
      timeout: 3000,
    })
    expect(check).toHaveTextContent('Network drive')
    expect(check).toHaveTextContent(
      'This is a network location. It can be slow.',
    )
    await waitFor(() => expect(addButton()).toBeEnabled())
  })

  it('explains a folder that will be created', async () => {
    inspections['/media/usb/new'] = inspection('/media/usb/new', {
      exists: false,
      is_dir: false,
      will_create: true,
      warnings: ["This folder doesn't exist yet, so Civex will create it."],
    })
    const user = userEvent.setup()
    renderIt()

    await fill(user, '/media/usb/new')

    const check = await screen.findByLabelText('Location check', undefined, {
      timeout: 3000,
    })
    expect(check).toHaveTextContent('New folder')
    expect(check).toHaveTextContent('Civex will create it')
  })

  it('validates the name', async () => {
    const user = userEvent.setup()
    renderIt(['default', 'archive'])

    await user.type(screen.getByLabelText(/volume name/i), 'my drive')
    expect(
      screen.getByText('Use only letters, digits, hyphens and underscores.'),
    ).toBeInTheDocument()

    await user.clear(screen.getByLabelText(/volume name/i))
    await user.type(screen.getByLabelText(/volume name/i), 'archive')
    expect(
      screen.getByText("A volume called 'archive' already exists."),
    ).toBeInTheDocument()
  })

  it('fills the folder from the folder browser', async () => {
    const user = userEvent.setup()
    renderIt()

    await user.click(screen.getByRole('button', { name: 'Browse…' }))
    expect(
      await screen.findByRole('heading', { name: 'Choose a folder' }),
    ).toBeInTheDocument()
    await user.click(
      await screen.findByRole('button', { name: 'Choose this folder' }),
    )

    expect(screen.getByLabelText(/^folder/i)).toHaveValue('/media/usb')
    expect(
      screen.getByRole('heading', { name: 'Location' }),
    ).toBeInTheDocument()
  })

  it('adds the volume with its limit and queue choice', async () => {
    const user = userEvent.setup()
    const { onClose } = renderIt()
    await fill(user, '/media/usb/civex')
    await user.click(
      screen.getByLabelText('Limit how much space Civex may use'),
    )
    await user.type(screen.getByLabelText('Space limit in GB'), '500')
    await user.click(screen.getByLabelText('Use it for new files in general'))
    await waitFor(() => expect(addButton()).toBeEnabled(), { timeout: 3000 })

    expect(screen.getByText(/in the write queue/)).toBeInTheDocument()
    await user.click(addButton())

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'POST',
        path: '/api/store/volumes',
        body: {
          name: 'archive',
          path: '/media/usb/civex',
          allocated_gb: 500,
          add_to_queue: true,
        },
      }),
    )
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('shows the server error and stays open', async () => {
    addResponse = () => json({ detail: 'Civex cannot write there.' }, 422)
    const user = userEvent.setup()
    const { onClose } = renderIt()
    await fill(user, '/media/usb/civex')
    await waitFor(() => expect(addButton()).toBeEnabled(), { timeout: 3000 })

    await user.click(addButton())

    expect(
      await screen.findByText('Civex cannot write there.'),
    ).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })
})
