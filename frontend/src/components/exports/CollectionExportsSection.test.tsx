import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ToastProvider } from '../ui/ToastProvider'
import { exported, fakeServer, finishExport } from '../files/testSupport'
import { CollectionExportsSection } from './CollectionExportsSection'
import { definition, SCHEMAS } from './exportsTestSupport'

afterEach(() => vi.unstubAllGlobals())

function serve(defs: unknown[] = [definition()]) {
  return fakeServer({
    '/api/file-access/definitions': defs,
    '/api/schemas': SCHEMAS,
    '/api/store/volumes': [],
    '/api/file-access/exports': [],
    '/api/file-access/export': exported(),
  })
}

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <CollectionExportsSection collection="hb" />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('a collection’s Exports tab', () => {
  it('asks the server for the exports saved with the collection’s schemas', async () => {
    const calls = serve()
    renderIt()

    await screen.findByText('Contours')

    expect(
      calls.find((c) => c.path === '/api/file-access/definitions'),
    ).toBeTruthy()
  })

  it('always offers all the files, and lists the saved exports', async () => {
    serve()
    renderIt()

    expect(await screen.findByText('All files')).toBeTruthy()
    expect(await screen.findByText('Contours')).toBeTruthy()
    expect(
      screen.getByText(/contour of selection · all in one folder/i),
    ).toBeTruthy()
  })

  it('says where an export is set up, with a way there', async () => {
    serve()
    renderIt()

    const link = await screen.findByRole('link', {
      name: /starts from encounter/i,
    })

    expect(link.getAttribute('href')).toBe('/exports?schema=encounter')
  })

  it('runs a saved export on this collection from its Export menu', async () => {
    const calls = serve()
    renderIt()
    const row = (await screen.findByText('Contours')).closest('li')!

    await userEvent.click(within(row).getByRole('button', { name: /^export/i }))
    await finishExport('folder', 0)

    await waitFor(() =>
      expect(calls.some((c) => c.path === '/api/file-access/export')).toBe(
        true,
      ),
    )
    expect(
      calls.find((c) => c.path === '/api/file-access/export')!.body,
    ).toMatchObject({
      export: 'encounter/Contours',
      collection: 'hb',
      name: 'hb-Contours',
      mode: 'link',
    })
  })

  it('runs the whole collection from its own row', async () => {
    const calls = serve()
    renderIt()
    const row = (await screen.findByText('All files')).closest('li')!

    await userEvent.click(within(row).getByRole('button', { name: /^export/i }))
    await finishExport('folder', 2)

    await waitFor(() =>
      expect(calls.some((c) => c.path === '/api/file-access/export')).toBe(
        true,
      ),
    )
    const sent = calls.find((c) => c.path === '/api/file-access/export')!.body
    expect(sent).toMatchObject({ collection: 'hb', name: 'hb-files' })
    expect(sent.export).toBeUndefined()
  })

  it('points to the Exports page when none are saved', async () => {
    serve([])
    renderIt()

    expect(await screen.findByText(/no saved exports/i)).toBeTruthy()
    expect(screen.getByText(/set them up on the exports page/i)).toBeTruthy()
    // Every file in the collection can still be exported.
    expect(screen.getByText('All files')).toBeTruthy()
  })

  it('also has the folders earlier exports made, to look after', async () => {
    serve()
    renderIt()

    expect(await screen.findByText(/^no exports$/i)).toBeTruthy()
  })
})
