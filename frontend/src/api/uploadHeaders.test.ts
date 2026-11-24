import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setMountedHost, type MountedHost } from '../utils/host'
import { filesApi } from './files'
import { recordsApi } from './records'

class FakeXhr {
  static last: FakeXhr
  headers: Record<string, string> = {}
  upload: Record<string, unknown> = {}
  url = ''
  constructor() {
    FakeXhr.last = this
  }
  open(_m: string, url: string) {
    this.url = url
  }
  setRequestHeader(k: string, v: string) {
    this.headers[k] = v
  }
  send() {}
  abort() {}
}

const mount = (headers?: MountedHost['headers']) =>
  setMountedHost({
    base: '/a/b/data',
    boot: {},
    headers,
    portal: document.body,
    root: document.body,
  })

const file = new File(['x'], 'a.wav')
const uploads: [string, () => unknown][] = [
  ['uploadBatch', () => filesApi.uploadBatch([file])],
  ['attachFile', () => recordsApi.attachFile('r/1', 'clip', file)],
]

beforeEach(() => {
  vi.stubGlobal('XMLHttpRequest', FakeXhr)
})
afterEach(() => {
  vi.unstubAllGlobals()
  setMountedHost(null)
  delete window.__CIVEX_HEADERS__
})

describe.each(uploads)('%s', (_name, upload) => {
  it('sends the mounted host headers', () => {
    mount(() => ({ Authorization: 'Bearer m' }))
    void upload()
    expect(FakeXhr.last.headers).toEqual({ Authorization: 'Bearer m' })
  })

  it('goes ahead without headers when headers() throws', () => {
    mount(() => {
      throw new Error('no token')
    })
    void upload()
    expect(FakeXhr.last.headers).toEqual({})
  })

  it('ignores window.__CIVEX_HEADERS__ when mounted without headers', () => {
    window.__CIVEX_HEADERS__ = () => ({ Authorization: 'Bearer w' })
    mount()
    void upload()
    expect(FakeXhr.last.headers).toEqual({})
  })
})

it('encodes the record id in the upload URL', () => {
  void recordsApi.attachFile('r/1', 'clip', file)
  expect(FakeXhr.last.url).toContain('/records/r%2F1/files/clip')
})
