import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router'
import { ToastProvider } from '../ui/ToastProvider'
import { FileAccessActions } from './FileAccessActions'
import { selectionFor } from '../../api/fileAccess'
import {
  exported,
  fakeServer,
  group,
  json,
  plan,
  refusal,
  transfer,
  volume,
} from './testSupport'

const SELECTION = { collection: 'hb', schema_name: 'selection' }
const GB = 1024 ** 3

let answer: () => Response
let planBody: Record<string, unknown>
let zipAnswer: () => Response

beforeEach(() => {
  planBody = plan()
  answer = () => json(exported())
  zipAnswer = () => new Response('zip', { status: 200 })
  URL.createObjectURL = () => 'blob:x'
  URL.revokeObjectURL = () => {}
})

afterEach(() => vi.unstubAllGlobals())

function serve() {
  return fakeServer({
    '/api/file-access/export': () => answer(),
    '/api/file-access/plan': () => json(planBody),
    '/api/file-access/zip': () => zipAnswer(),
    '/api/file-access/gather': {
      transfer_id: 't1',
      volume: 'archive',
      files: 1,
      bytes: GB,
    },
    '/api/store/transfers/t1': () => json(transfer()),
    '/api/store/volumes': [
      volume('default', 10 * GB),
      volume('archive', 20 * GB),
    ],
    '/api/file-access/exports': [],
    '/api/schemas': [],
  })
}

function Where() {
  return (
    <span data-testid="where">
      {useLocation().pathname + useLocation().search}
    </span>
  )
}

function renderIt(selection: Record<string, unknown> = SELECTION) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <FileAccessActions selection={selection} folderName="hb-selection" />
          <Where />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

async function choose(item: RegExp) {
  await userEvent.click(screen.getByRole('button', { name: /^export$/i }))
  await userEvent.click(screen.getByRole('menuitem', { name: item }))
}

const next = () =>
  userEvent.click(screen.getByRole('button', { name: /^next/i }))

/** Files → Export files… → (what, layout as they are) → pick a method → go. */
async function exportVia(method: 'folder' | 'copy' | 'zip') {
  await choose(/^export…/i)
  await next()
  await next()
  const names = {
    folder: [/open as folder/i, /^open folder$/i],
    copy: [/copy to a drive/i, /^copy$/i],
    zip: [/download zip/i, /^download$/i],
  }[method]
  await userEvent.click(screen.getByRole('radio', { name: names[0] }))
  await userEvent.click(screen.getByRole('button', { name: names[1] }))
}

const scattered = (over: Record<string, unknown> = {}) =>
  plan({
    scattered: true,
    link_volume: null,
    by_volume: [
      { volume: 'archive', files: 3, bytes: 3 * GB },
      { volume: 'default', files: 1, bytes: 1 * GB },
    ],
    available_bytes: 4 * GB,
    bytes: 4 * GB,
    ...over,
  })

const unreachable = (over: Record<string, unknown> = {}) =>
  plan({ available: 3, complete: false, unavailable: [group()], ...over })

// The dialog also reads the drives' free space, and shows a preview on its last
// step (a plan with the files listed); neither is what is being asked.
const mine = <T extends { path: string; body?: Record<string, unknown> }>(
  calls: T[],
) =>
  calls.filter(
    (c) =>
      c.path !== '/api/store/volumes' &&
      c.path !== '/api/schemas' &&
      !(c.path === '/api/file-access/plan' && c.body?.include_items === true),
  )
const callPaths = (calls: { path: string }[]) => mine(calls).map((c) => c.path)

describe('the Files menu', () => {
  it('explains each choice', async () => {
    serve()
    renderIt()

    await userEvent.click(screen.getByRole('button', { name: /^export$/i }))

    expect(screen.getAllByRole('menuitem').map((i) => i.textContent)).toEqual([
      expect.stringMatching(/^export…/i),
      expect.stringMatching(/manage exports/i),
    ])
  })

  it('takes you to the exports, which are on a page, not in a pop-up', async () => {
    serve()
    renderIt()

    await choose(/manage exports/i)

    expect(screen.getByTestId('where').textContent).toBe('/exports?tab=made')
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('exports saved for the schema', () => {
  const PRESETS = [
    {
      label: 'Contour files',
      hint: 'contour · all in one folder',
      selection: { export: 'encounter/Contours', within: 'e7' },
      folderName: 'Encounter 7-Contours',
    },
  ]

  function renderWithPresets() {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <MemoryRouter>
            <FileAccessActions
              selection={{ within: 'e7' }}
              folderName="Encounter 7"
              presets={PRESETS}
              builderTo="/exports?schema=s1"
            />
            <Where />
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    )
  }

  it('are offered first, each saying what it takes and how it is laid out', async () => {
    serve()
    renderWithPresets()

    await userEvent.click(screen.getByRole('button', { name: /^export$/i }))

    expect(screen.getAllByRole('menuitem').map((i) => i.textContent)).toEqual([
      expect.stringMatching(/contour files.*contour · all in one folder/i),
      expect.stringMatching(/^export…/i),
      expect.stringMatching(/set up exports/i),
      expect.stringMatching(/manage exports/i),
    ])
  })

  it('open the builder filled in, at the method, and run on the record', async () => {
    const calls = serve()
    renderWithPresets()

    await choose(/contour files/i)
    await userEvent.click(
      screen.getByRole('radio', { name: /open as folder/i }),
    )
    await userEvent.click(
      screen.getByRole('button', { name: /^open folder$/i }),
    )

    await waitFor(() => expect(mine(calls)).toHaveLength(1))
    expect(mine(calls)[0].body).toMatchObject({
      export: 'encounter/Contours',
      within: 'e7',
      name: 'Encounter 7-Contours',
      mode: 'link',
    })
  })

  it('lead to where exports are set up, which is the schema', async () => {
    serve()
    renderWithPresets()

    await choose(/set up exports/i)

    expect(screen.getByTestId('where').textContent).toBe('/exports?schema=s1')
  })

  it('leave the menu as it was where there are none', async () => {
    serve()
    renderIt()

    await userEvent.click(screen.getByRole('button', { name: /^export$/i }))

    expect(
      screen.queryByRole('menuitem', { name: /set up exports/i }),
    ).toBeNull()
    expect(screen.getByRole('menuitem', { name: /^export…/i })).toBeTruthy()
  })
})

describe('the menu is organised by what you want', () => {
  it('groups the actions under headings, with the saved exports first', async () => {
    serve()
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ToastProvider>
          <MemoryRouter>
            <FileAccessActions
              selection={{ within: 'e7' }}
              folderName="Encounter 7"
              presets={[
                {
                  label: 'Contour files',
                  hint: 'contour of Selection · all in one folder',
                  selection: { export: 'encounter/Contours', within: 'e7' },
                  folderName: 'x',
                },
              ]}
              builderTo="/exports?schema=s1"
            />
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    )

    await userEvent.click(screen.getByRole('button', { name: /^export$/i }))

    const menu = screen.getByRole('menu')
    expect(
      Array.from(menu.children).map((c) =>
        c.getAttribute('role') === 'separator'
          ? '---'
          : (c.textContent ?? '').slice(0, 12),
      ),
    ).toEqual([
      'Saved export',
      'Contour file',
      '---',
      'Export…Take ',
      '---',
      'Set up expor',
      'Manage expor',
    ])
  })

  it('has no saved-exports heading when there are none', async () => {
    serve()
    renderIt()

    await userEvent.click(screen.getByRole('button', { name: /^export$/i }))

    const menu = screen.getByRole('menu')
    expect(within(menu).queryByText('Saved exports')).toBeNull()
  })

  it('has icons that are all the same size, in the same box', async () => {
    serve()
    renderIt()

    await userEvent.click(screen.getByRole('button', { name: /^export$/i }))

    const icons = within(screen.getByRole('menu'))
      .getAllByRole('menuitem')
      .map((item) => item.querySelector('svg')!)
    expect(icons.length).toBe(2)
    expect(new Set(icons.map((i) => i.getAttribute('width'))).size).toBe(1)
    expect(icons[0].getAttribute('width')).toBe('18')
    // And they are not the little ones the buttons use.
    const trigger = screen.getByRole('button', { name: /^export$/i })
    for (const svg of Array.from(trigger.querySelectorAll('svg')))
      expect(svg.getAttribute('width')).toBe('16')
  })
})

describe('Open in folder', () => {
  it('is one request when nothing is in the way, and no dialog', async () => {
    const calls = serve()
    renderIt()

    await exportVia('folder')

    await screen.findByText(/opened a folder of 4 files \(4 linked\)/i)
    // No separate "checking" request first: the answer to the export says.
    expect(callPaths(calls)).toEqual(['/api/file-access/export'])
    expect(mine(calls)[0].body).toMatchObject({
      ...SELECTION,
      name: 'hb-selection',
      mode: 'link',
      allow_partial: false,
      open: true,
    })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByText(/don’t edit them in place/i)).toBeTruthy()
  })

  it('says which drive a folder was made on', async () => {
    answer = () => json(exported({ location: 'archive', linked: 2, copied: 1 }))
    serve()
    renderIt()

    await exportVia('folder')

    expect(
      await screen.findByText(/\(2 linked, 1 copied\) on archive/i),
    ).toBeTruthy()
  })

  it('offers the folder path when the server could not open it here', async () => {
    answer = () => json(exported({ opened: false }))
    serve()
    renderIt()

    await exportVia('folder')

    expect(
      await screen.findByText(
        /ready at \/proj\/_civex\/exports\/hb-selection/i,
      ),
    ).toBeTruthy()
    expect(screen.getByRole('button', { name: /copy path/i })).toBeTruthy()
  })

  it('carries a saved view’s layout and a saved view itself', async () => {
    const calls = serve()
    renderIt({ view: 'recording/tables', layout: 'flat' })

    await exportVia('folder')

    await waitFor(() => expect(mine(calls)).toHaveLength(1))
    expect(mine(calls)[0].body).toMatchObject({
      view: 'recording/tables',
      layout: 'flat',
      mode: 'link',
    })
  })
})

describe('when files cannot be reached', () => {
  beforeEach(() => {
    answer = () => refusal('files_unavailable', { plan: unreachable() })
  })

  it('opens one dialog from the answer itself, with nothing built or asked again', async () => {
    const calls = serve()
    renderIt()

    await exportVia('folder')

    expect(await screen.findByText(/1 file can’t be reached/i)).toBeTruthy()
    expect(screen.getByText(/on “archive”/)).toBeTruthy()
    expect(screen.getByText(/plug in the drive called archive/i)).toBeTruthy()
    expect(screen.getByText(/nothing has been opened yet/i)).toBeTruthy()
    expect(callPaths(calls)).toEqual(['/api/file-access/export'])
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
  })

  it('goes ahead with the rest only when you say so', async () => {
    const calls = serve()
    renderIt()
    await exportVia('folder')
    answer = () =>
      json(exported({ linked: 3, missing: [{ path: 'a', reason: 'x' }] }))

    await userEvent.click(
      await screen.findByRole('button', { name: /open the 3 available/i }),
    )

    await waitFor(() => expect(mine(calls)).toHaveLength(2))
    expect(mine(calls)[1].body).toMatchObject({
      mode: 'link',
      allow_partial: true,
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(await screen.findByText(/1 file left out/i)).toBeTruthy()
  })

  it('checks again inside the same dialog, so a drive plugged in meanwhile counts', async () => {
    const calls = serve()
    renderIt()
    await exportVia('folder')
    await screen.findByRole('button', { name: /check again/i })

    planBody = plan() // the drive is back
    await userEvent.click(screen.getByRole('button', { name: /check again/i }))

    await waitFor(() =>
      expect(callPaths(calls)).toEqual([
        '/api/file-access/export',
        '/api/file-access/plan',
      ]),
    )
    // Nothing is missing now: the same dialog offers to open it all.
    expect(
      await screen.findByRole('button', { name: /^open folder$/i }),
    ).toBeTruthy()
    expect(screen.queryByText(/can’t be reached/i)).toBeNull()
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
  })

  it('cancelling builds nothing', async () => {
    const calls = serve()
    renderIt()
    await exportVia('folder')

    await userEvent.click(
      await screen.findByRole('button', { name: /cancel/i }),
    )

    expect(callPaths(calls)).toEqual(['/api/file-access/export'])
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('has nothing to go ahead with when nothing is reachable', async () => {
    answer = () =>
      refusal('files_unavailable', {
        plan: plan({
          available: 0,
          complete: false,
          by_volume: [],
          link_volume: null,
          unavailable: [group({ volume: null, files: 4 })],
        }),
      })
    serve()
    renderIt()
    await exportVia('folder')

    const go = await screen.findByRole('button', { name: /the 0 available/i })

    expect((go as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('when files are spread over several drives', () => {
  beforeEach(() => {
    answer = () => refusal('files_scattered', { plan: scattered() })
  })

  it('offers every way forward in the one dialog', async () => {
    const calls = serve()
    renderIt()

    await exportVia('folder')

    expect(
      await screen.findByText(/4 files .* on archive \(3\), default \(1\)/i),
    ).toBeTruthy()
    // A link can't gather them, and says why; moving just these is the default.
    const link = screen.getByRole('radio', {
      name: /link them where they are/i,
    })
    expect((link as HTMLInputElement).disabled).toBe(true)
    expect(screen.getByText(/they are on 2 drives/i)).toBeTruthy()
    expect(
      (
        screen.getByRole('radio', {
          name: /move them onto one drive/i,
        }) as HTMLInputElement
      ).checked,
    ).toBe(true)
    expect(
      screen.getByText(/only these files, not the rest of their collections/i),
    ).toBeTruthy()
    expect(
      screen.getByRole('radio', { name: /copy them onto a drive/i }),
    ).toBeTruthy()
    // The drive that holds most is suggested, with what is free.
    const picker = screen.getByRole('combobox', {
      name: 'Move them onto',
    }) as HTMLSelectElement
    await waitFor(() => expect(picker.value).toBe('archive'))
    expect(
      screen.getByRole('button', { name: /move 1 file and open/i }),
    ).toBeTruthy()
    expect(callPaths(calls)).toEqual(['/api/file-access/export'])
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
  })

  it('moves just those files, then links and opens, as one action', async () => {
    const calls = serve()
    renderIt()
    await exportVia('folder')
    await screen.findByRole('button', { name: /move 1 file and open/i })
    answer = () => json(exported({ location: 'archive', linked: 4 }))

    await userEvent.click(
      screen.getByRole('button', { name: /move 1 file and open/i }),
    )

    expect(
      await screen.findByText(
        /opened a folder of 4 files \(4 linked\) on archive/i,
      ),
    ).toBeTruthy()
    expect(callPaths(calls)).toEqual([
      '/api/file-access/export',
      '/api/file-access/gather',
      '/api/store/transfers/t1',
      '/api/file-access/export',
    ])
    expect(mine(calls)[1].body).toMatchObject({
      ...SELECTION,
      volume: 'archive',
    })
    expect(mine(calls)[3].body).toMatchObject({
      mode: 'link',
      allow_partial: true,
    })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('shows the free space and refuses a move that cannot fit', async () => {
    answer = () => refusal('files_scattered', { plan: scattered() })
    fakeServer({
      '/api/schemas': [],
      '/api/file-access/export': () => answer(),
      '/api/store/volumes': [
        volume('archive', GB / 2),
        volume('default', 10 * GB),
      ],
    })
    renderIt()
    await exportVia('folder')

    const alert = await screen.findByRole('alert')

    expect(alert.textContent).toMatch(
      /needs 1\.0 GB.*“archive” has 512 MB free/i,
    )
    expect(
      (
        screen.getByRole('button', {
          name: /move 1 file and open/i,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true)
  })

  it('copies instead, onto the drive you choose', async () => {
    const calls = serve()
    renderIt()
    await exportVia('folder')
    await userEvent.click(
      await screen.findByRole('radio', { name: /copy them onto a drive/i }),
    )
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Copy onto' }),
      'default',
    )
    answer = () => json(exported({ location: 'default', linked: 0, copied: 4 }))

    await userEvent.click(screen.getByRole('button', { name: /copy 4 files/i }))

    expect(await screen.findByText(/\(4 copied\) on default/i)).toBeTruthy()
    expect(mine(calls)[mine(calls).length - 1].body).toMatchObject({
      mode: 'copy',
      volume: 'default',
      allow_partial: true,
    })
    expect(screen.queryByText(/don’t edit them in place/i)).toBeNull()
  })

  it('does not stop a zip, which gathers from any drive', async () => {
    zipAnswer = () => new Response('zip', { status: 200 })
    const calls = serve()
    renderIt()

    await exportVia('zip')

    await waitFor(() =>
      expect(callPaths(calls)).toEqual(['/api/file-access/zip']),
    )
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('when the drive cannot make links', () => {
  it('fetches the plan, says so, and starts from a copy', async () => {
    answer = () =>
      refusal('links_not_possible', {}, 'A linked folder can’t be made here.')
    planBody = plan()
    const calls = serve()
    renderIt()

    await exportVia('folder')

    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByRole('alert').textContent).toMatch(/can’t be made here/i)
    expect(
      (
        screen.getByRole('radio', {
          name: /copy them onto a drive/i,
        }) as HTMLInputElement
      ).checked,
    ).toBe(true)
    expect(callPaths(calls)).toEqual([
      '/api/file-access/export',
      '/api/file-access/plan',
    ])
  })
})

describe('Copy to a drive', () => {
  it('is a method of the export, with the drive chosen beside it', async () => {
    const calls = serve()
    renderIt()

    await choose(/^export…/i)
    await next()
    await next()
    await userEvent.click(
      screen.getByRole('radio', { name: /copy to a drive/i }),
    )
    await userEvent.selectOptions(
      await screen.findByRole('combobox', { name: /copy onto/i }),
      'archive',
    )
    await userEvent.click(screen.getByRole('button', { name: /^copy$/i }))

    await waitFor(() =>
      expect(callPaths(calls)).toContain('/api/file-access/export'),
    )
    expect(
      calls.find((c) => c.path === '/api/file-access/export')!.body,
    ).toMatchObject({ mode: 'copy', volume: 'archive' })
  })

  it('copies into the project folder when no drive is chosen', async () => {
    const calls = serve()
    renderIt()

    await exportVia('copy')

    await waitFor(() =>
      expect(callPaths(calls)).toContain('/api/file-access/export'),
    )
    const body = calls.find((c) => c.path === '/api/file-access/export')!.body
    expect(body.mode).toBe('copy')
    expect(body.volume).toBeUndefined()
  })
})

describe('one dialog for every way of getting the files', () => {
  it('offers the three methods together, and no menu items for them', async () => {
    serve()
    renderIt()

    await choose(/^export…/i)
    await next()
    await next()

    expect(
      screen
        .getAllByRole('radio', { name: /folder|drive|zip/i })
        .map((r) => r.getAttribute('aria-label')),
    ).toEqual(['Open as folder', 'Copy to a drive', 'Download zip'])
  })

  it('walks through what, layout, then how', async () => {
    serve()
    renderIt()

    await choose(/^export…/i)

    expect(screen.getByText('What goes in the folder')).toBeTruthy()
    await next()
    expect(screen.getByRole('radiogroup', { name: /layout/i })).toBeTruthy()
    await next()
    expect(screen.getByRole('radiogroup', { name: /method/i })).toBeTruthy()
  })
})

describe('Download zip', () => {
  it('lists what is out of reach before downloading, then downloads the rest', async () => {
    zipAnswer = () => refusal('files_unavailable', { plan: unreachable() })
    const calls = serve()
    renderIt()
    await exportVia('zip')

    expect(await screen.findByText(/download these files/i)).toBeTruthy()
    expect(screen.queryByRole('radio')).toBeNull() // a zip needs no choice of how
    zipAnswer = () => new Response('zip', { status: 200 })
    await userEvent.click(
      screen.getByRole('button', { name: /download the 3 available/i }),
    )

    await waitFor(() => expect(mine(calls)).toHaveLength(2))
    expect(mine(calls)[1].body).toMatchObject({ allow_partial: true })
  })
})

describe('selectionFor', () => {
  it('uses the explorer’s current query', () => {
    expect(
      selectionFor(
        { schema: 'selection', within: 'e7', search: 'x', where: ['a=1'] },
        'hb',
      ),
    ).toEqual({
      collection: 'hb',
      layout: undefined,
      schema_name: 'selection',
      within: 'e7',
      filter: undefined,
      where: ['a=1'],
      search: 'x',
    })
  })

  it('carries the active view’s layout, for ticked rows as well', () => {
    expect(
      selectionFor({ schema: 'selection' }, 'hb', undefined, 'flat'),
    ).toMatchObject({
      layout: 'flat',
    })
    expect(selectionFor({ schema: 'selection' }, 'hb', ['r1'], 'flat')).toEqual(
      {
        collection: 'hb',
        record_ids: ['r1'],
        layout: 'flat',
      },
    )
  })

  it('uses exactly the ticked rows when there are some', () => {
    expect(
      selectionFor({ schema: 'selection' }, 'hb', ['r1', 'r2']),
    ).toMatchObject({
      collection: 'hb',
      record_ids: ['r1', 'r2'],
    })
  })
})
