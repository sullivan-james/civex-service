import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { ToastProvider } from '../components/ui'
import NewRecordPage from './NewRecordPage'

const field = (name: string, type: string, required = false) => ({
  id: `f-${name}`,
  name,
  label: null,
  type,
  required,
  restrictions: type === 'integer' ? { min: 0, max: 10 } : {},
  default: null,
  position: 0,
})
const SCHEMAS = [
  {
    id: 's1',
    name: 'encounter',
    label: null,
    description: null,
    parent_id: null,
    display_template: null,
    deleted_at: null,
    fields: [field('site', 'string', true), field('depth', 'integer')],
  },
]
const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

let posted: unknown
let posts: unknown[]
beforeEach(() => {
  posted = null
  posts = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      if (init?.method === 'POST' && url.pathname.endsWith('/records')) {
        posted = JSON.parse(String(init.body))
        posts.push(posted)
        return json({ id: 'new1', natural_name: 'N', data: {} })
      }
      if (url.pathname === '/api/records/p1')
        return json({
          id: 'p1',
          dataset_id: 'c',
          schema_name: 'encounter',
          natural_name: 'Parent',
          data: {},
          ancestors: [],
        })
      if (url.pathname === '/api/schemas') return json(SCHEMAS)
      if (url.pathname === '/api/collections/hb')
        return json({ id: 'c', name: 'hb', description: null, record_count: 0 })
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

describe('NewRecordPage', () => {
  it('shows blank rows with their rules, and adds what was filled in', async () => {
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ToastProvider>
          <MemoryRouter
            initialEntries={['/collections/hb/new?schema=encounter']}
          >
            <Routes>
              <Route path="/collections/:id/new" element={<NewRecordPage />} />
              <Route path="/records/:id" element={<p>created</p>} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    )
    expect(await screen.findByText('0 – 10')).toBeInTheDocument()

    await user.click(screen.getAllByTitle('Click to edit')[0])
    await user.type(screen.getByRole('textbox'), 'Stellwagen{Enter}')
    await user.click(screen.getByRole('button', { name: 'Add encounter' }))

    await waitFor(() => expect(posted).not.toBeNull())
    expect(posted).toMatchObject({
      schema_name: 'encounter',
      data: { site: 'Stellwagen' },
    })
    expect(await screen.findByText('created')).toBeInTheDocument()
  })

  function renderAt(entries: string[]) {
    return render(
      <QueryClientProvider client={new QueryClient()}>
        <ToastProvider>
          <MemoryRouter
            initialEntries={entries}
            initialIndex={entries.length - 1}
          >
            <Routes>
              <Route path="/collections/:id/new" element={<NewRecordPage />} />
              <Route path="/collections/:id" element={<p>collection list</p>} />
              <Route path="/records/:id" element={<p>record page</p>} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    )
  }

  it('Cancel returns to where the person came from', async () => {
    const user = userEvent.setup()
    renderAt([
      '/collections/hb?schema=encounter&q=whale',
      '/collections/hb/new?schema=encounter',
    ])
    await user.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(await screen.findByText('collection list')).toBeInTheDocument()
  })

  it('Cancel with nothing behind it goes to the parent record', async () => {
    const user = userEvent.setup()
    renderAt(['/collections/hb/new?schema=encounter&parent=p1'])
    await user.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(await screen.findByText('record page')).toBeInTheDocument()
  })

  describe('Add and add another', () => {
    async function fill(
      user: ReturnType<typeof userEvent.setup>,
      text: string,
    ) {
      await user.click(screen.getAllByTitle('Click to edit')[0])
      await user.type(screen.getByRole('textbox'), `${text}{Enter}`)
    }

    it('saves, stays on a blank form for the next one, and says what was added', async () => {
      const user = userEvent.setup()
      renderAt(['/collections/hb/new?schema=encounter'])
      await screen.findByText('0 – 10')

      await fill(user, 'Stellwagen')
      await user.click(
        screen.getByRole('button', { name: 'Add and add another' }),
      )

      await waitFor(() => expect(posts).toHaveLength(1))
      expect(posts[0]).toMatchObject({ data: { site: 'Stellwagen' } })
      // still on the form (not the record page), with a confirmation
      expect(screen.queryByText('record page')).toBeNull()
      expect(await screen.findByText('Added N.')).toBeInTheDocument()
      // blank again: the last record's value is not carried over
      expect(screen.queryByText('Stellwagen')).toBeNull()

      await fill(user, 'Georges')
      await user.click(screen.getByRole('button', { name: 'Add encounter' }))

      await waitFor(() => expect(posts).toHaveLength(2))
      expect(posts[1]).toEqual(
        expect.objectContaining({ data: { site: 'Georges' } }),
      )
      expect(await screen.findByText('record page')).toBeInTheDocument()
    })

    it('keeps the parent the list fixed, so a run of records goes under the same one', async () => {
      const user = userEvent.setup()
      renderAt(['/collections/hb/new?schema=encounter&parent=p1'])
      await screen.findByText('0 – 10')

      await fill(user, 'A')
      await user.click(
        screen.getByRole('button', { name: 'Add and add another' }),
      )
      await waitFor(() => expect(posts).toHaveLength(1))
      await screen.findByText('Added N.')
      await fill(user, 'B')
      await user.click(
        screen.getByRole('button', { name: 'Add and add another' }),
      )

      await waitFor(() => expect(posts).toHaveLength(2))
      expect(
        posts.map((p) => (p as { parent_record_id: string }).parent_record_id),
      ).toEqual(['p1', 'p1'])
    })

    it('does not stay on the form when it could not save', async () => {
      const user = userEvent.setup()
      vi.stubGlobal(
        'fetch',
        vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
          const url = new URL(String(input), 'http://x')
          if (init?.method === 'POST' && url.pathname.endsWith('/records'))
            return new Response(
              JSON.stringify({ detail: 'site is required' }),
              {
                status: 422,
                headers: { 'Content-Type': 'application/json' },
              },
            )
          if (url.pathname === '/api/schemas') return json(SCHEMAS)
          if (url.pathname === '/api/collections/hb')
            return json({
              id: 'c',
              name: 'hb',
              description: null,
              record_count: 0,
            })
          return json({})
        }),
      )
      renderAt(['/collections/hb/new?schema=encounter'])
      await screen.findByText('0 – 10')

      await user.click(
        screen.getByRole('button', { name: 'Add and add another' }),
      )

      expect(await screen.findByText(/site is required/)).toBeInTheDocument()
      expect(screen.queryByText(/^Added/)).toBeNull()
    })
  })

  describe('files chosen before Add', () => {
    const WITH_FILE = [
      {
        ...SCHEMAS[0],
        fields: [field('site', 'string'), field('reading', 'file')],
      },
    ]
    let sent: { record: unknown; files: string[] } | null
    let answer: Response

    beforeEach(() => {
      sent = null
      answer = json({ id: 'new1', natural_name: 'N', data: {} })
      vi.stubGlobal(
        'fetch',
        vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
          const url = new URL(String(input), 'http://x')
          if (url.pathname.endsWith('/records/with-files')) {
            const form = init?.body as FormData
            sent = {
              record: JSON.parse(String(form.get('record'))),
              files: form.getAll('reading').map((f) => (f as File).name),
            }
            return answer
          }
          if (url.pathname.startsWith('/api/files'))
            throw new Error('a file must not be stored before the record is')
          if (url.pathname === '/api/schemas') return json(WITH_FILE)
          if (url.pathname === '/api/collections/hb')
            return json({
              id: 'c',
              name: 'hb',
              description: null,
              record_count: 0,
            })
          return json({})
        }),
      )
    })

    it('holds the file in the field and sends it with the record', async () => {
      const user = userEvent.setup()
      renderAt(['/collections/hb/new?schema=encounter'])
      await screen.findByLabelText('Add Reading')

      await user.upload(
        screen.getByLabelText('Add Reading'),
        new File(['abc'], 'a.csv'),
      )
      expect(await screen.findByText('a.csv')).toBeInTheDocument()
      expect(screen.getByText('not added yet')).toBeInTheDocument()
      expect(sent).toBeNull()

      await user.click(screen.getByRole('button', { name: 'Add encounter' }))
      await screen.findByText('record page')
      expect(sent).toEqual({
        record: { schema_name: 'encounter', data: {} },
        files: ['a.csv'],
      })
    })

    it('shows a refusal under the field, with nothing stored', async () => {
      const user = userEvent.setup()
      answer = new Response(
        JSON.stringify({
          detail:
            "Field 'reading': 'a.csv' type '.csv' not allowed — accepted: .wav",
        }),
        { status: 422, headers: { 'Content-Type': 'application/json' } },
      )
      renderAt(['/collections/hb/new?schema=encounter'])
      await screen.findByLabelText('Add Reading')
      await user.upload(
        screen.getByLabelText('Add Reading'),
        new File(['abc'], 'a.csv'),
      )

      await user.click(screen.getByRole('button', { name: 'Add encounter' }))

      expect(
        await screen.findByText(/isn't an accepted file type/),
      ).toBeInTheDocument()
      expect(screen.queryByText('record page')).toBeNull()
      // The file is still held, for another try.
      expect(screen.getByText('not added yet')).toBeInTheDocument()
    })
  })
})
