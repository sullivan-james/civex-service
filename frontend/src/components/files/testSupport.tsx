import { vi } from 'vitest'

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

export const plan = (over: Record<string, unknown> = {}) => ({
  total: 4,
  available: 4,
  bytes: 4000,
  available_bytes: 4000,
  complete: true,
  scattered: false,
  link_volume: 'default',
  by_volume: [{ volume: 'default', files: 4, bytes: 4000 }],
  summary: '',
  unavailable: [],
  tables: [],
  ...over,
})

export const group = (over: Record<string, unknown> = {}) => ({
  volume: 'archive',
  state: 'offline',
  reason: 'Drive “archive” is not connected.',
  fix: 'Plug in the drive called archive.',
  files: 1,
  bytes: 10,
  records: ['Selection 9'],
  ...over,
})

export const exported = (over: Record<string, unknown> = {}) => ({
  dest: '/proj/_civex/exports/hb-selection',
  location: 'project',
  linked: 4,
  copied: 0,
  unchanged: 0,
  removed: 0,
  missing: [],
  complete: true,
  opened: true,
  ...over,
})

export const volume = (name: string, free: number | null = 50e9) => ({
  name,
  path: `/mnt/${name}`,
  allocated_gb: null,
  civex_used_bytes: 0,
  disk_free_bytes: free,
  disk_total_bytes: 100e9,
  available: true,
  state: 'online',
  reason: '',
  fix: '',
  warning: false,
  in_queue: true,
  network: false,
  unused_files: 0,
  unused_bytes: 0,
  history_files: 0,
  history_bytes: 0,
})

export interface Call {
  path: string
  body: Record<string, unknown>
  method: string
  headers: Record<string, string>
}

type Answer =
  | unknown
  | ((
      body: Record<string, unknown>,
      method: string,
    ) => Response | Promise<Response>)

/** Stand-in for the server: `routes` maps an API path to what it answers (a
 * value, or a function of the request body and method, which may take its time);
 * every call is recorded, headers included. */
export function fakeServer(routes: Record<string, Answer>) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), 'http://x').pathname
      const body = JSON.parse(String(init?.body ?? '{}'))
      const method = init?.method ?? 'GET'
      const headers = Object.fromEntries(
        new Headers(init?.headers as HeadersInit | undefined).entries(),
      )
      calls.push({ path, body, method, headers })
      // A route may be given for a prefix (`/api/x/progress` answers
      // `/api/x/progress/<id>`).
      const key =
        path in routes
          ? path
          : Object.keys(routes).find((k) => path.startsWith(`${k}/`))
      const answer = key ? routes[key] : undefined
      if (typeof answer === 'function')
        return await (
          answer as (
            b: Record<string, unknown>,
            m: string,
          ) => Response | Promise<Response>
        )(body, method)
      return json(answer ?? {})
    }),
  )
  return calls
}

/** The server's refusal of an export it can explain: nothing was built. */
export const refusal = (
  code: 'files_unavailable' | 'files_scattered' | 'links_not_possible',
  body: Record<string, unknown> = {},
  detail = 'It can’t be done as asked.',
) => json({ detail, code, ...body }, 409)

export const transfer = (over: Record<string, unknown> = {}) => ({
  id: 't1',
  kind: 'files',
  status: 'completed',
  auto_resume: false,
  spec: { kind: 'files', targets: ['archive'], shas: ['a'], sources: [] },
  progress: {
    files_total: 1,
    files_done: 1,
    files_skipped: 0,
    files_failed: 0,
    bytes_total: 1000,
    bytes_done: 1000,
    current: null,
    current_bytes: 0,
    current_total: 0,
    rate_bytes_per_second: 0,
    eta_seconds: null,
    message: '',
  },
  ...over,
})

/** In the open export dialog: through the steps (what, layout) to the method, then go. */
export async function finishExport(
  method: 'folder' | 'copy' | 'zip' = 'folder',
  steps = 2,
) {
  const { screen, within } = await import('@testing-library/react')
  const userEvent = (await import('@testing-library/user-event')).default
  // Inside the dialog when there is one (a list behind it has its own Next).
  const box = () => {
    const d = screen.queryByRole('dialog')
    return d ? within(d) : screen
  }
  for (let i = 0; i < steps; i++)
    await userEvent.click(await box().findByRole('button', { name: /^next:/i }))
  const [radio, button] = {
    folder: [/open as folder/i, /^open folder$/i],
    copy: [/copy to a drive/i, /^copy$/i],
    zip: [/download zip/i, /^download$/i],
  }[method]
  await userEvent.click(await box().findByRole('radio', { name: radio }))
  await userEvent.click(box().getByRole('button', { name: button }))
}
