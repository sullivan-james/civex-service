import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api, ApiError } from './client'

let sent: { url: string; init: RequestInit }[]

beforeEach(() => {
  sent = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      sent.push({ url, init })
      return new Response('{}', {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

const header = (name: string) =>
  new Headers(sent[0].init.headers as HeadersInit).get(name)

// The server reads a body as JSON only if told it is: without this header every
// create, edit and restore is refused with "Request validation failed".
describe('api client headers', () => {
  it.each([
    ['post', () => api.post('/x', { a: 1 })],
    ['patch', () => api.patch('/x', { a: 1 })],
    ['put', () => api.put('/x', { a: 1 })],
  ])('%s sends its body as JSON', async (_name, call) => {
    await call()
    expect(header('Content-Type')).toBe('application/json')
  })

  it('keeps JSON when extra headers are given as undefined', async () => {
    await api.post('/x', {}, undefined)
    expect(header('Content-Type')).toBe('application/json')
    await api.patch('/x', {}, undefined)
    expect(
      new Headers(sent[1].init.headers as HeadersInit).get('Content-Type'),
    ).toBe('application/json')
  })

  it('sends a batch header alongside JSON', async () => {
    await api.post(
      '/x',
      {},
      {
        'Content-Type': 'application/json',
        'X-Civex-Batch': 'b1',
      },
    )
    expect(header('Content-Type')).toBe('application/json')
    expect(header('X-Civex-Batch')).toBe('b1')
  })

  it('leaves an upload without a content type, for the browser to set', async () => {
    await api.upload('/x', new FormData())
    expect(header('Content-Type')).toBeNull()
  })

  it('a get needs no body type but is still given the default', async () => {
    await api.get('/x')
    expect(sent[0].init.method).toBeUndefined()
  })
})

describe('api client errors', () => {
  it('carry the whole response body, for refusals that explain themselves', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              detail: 'These files are on 2 drives',
              code: 'files_scattered',
              plan: { total: 4 },
            }),
            { status: 409, headers: { 'Content-Type': 'application/json' } },
          ),
      ),
    )

    const err = (await api.post('/x', {}).catch((e) => e)) as ApiError

    expect(err.status).toBe(409)
    expect(err.message).toBe('These files are on 2 drives')
    expect(err.body).toEqual({
      detail: 'These files are on 2 drives',
      code: 'files_scattered',
      plan: { total: 4 },
    })
  })

  it('have an empty body when the response had none', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('', { status: 500 })),
    )

    const err = (await api.get('/x').catch((e) => e)) as ApiError

    expect(err.status).toBe(500)
    expect(err.body).toEqual({})
  })
})

describe('an answer that is a web page, not data', () => {
  it('says the server may be older than the page, instead of a parse error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response('<!doctype html><html></html>', {
            status: 200,
            headers: { 'Content-Type': 'text/html; charset=utf-8' },
          }),
      ),
    )
    const error = (await api
      .get('/remote/files')
      .catch((e: unknown) => e)) as ApiError
    expect(error).toBeInstanceOf(ApiError)
    expect(error.message).toMatch(/older version of civex than this page/)
  })
})
