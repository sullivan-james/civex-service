import { describe, expect, it } from 'vitest'
import { approvalUrl, parseHubAddress } from './hubAddress'

describe('parseHubAddress', () => {
  it('takes the browser address and the sync address alike', () => {
    for (const raw of [
      'https://hub.example/ada/notes',
      'https://hub.example/ada/notes/',
      'https://hub.example/ada/notes/data',
      ' hub.example/ada/notes ',
    ]) {
      expect(parseHubAddress(raw)).toMatchObject({
        address: 'https://hub.example/ada/notes/data',
        name: 'ada/notes',
        page: 'https://hub.example/ada/notes',
      })
    }
  })
  it('keeps a bare server as it is', () => {
    expect(parseHubAddress('http://localhost:8001')).toMatchObject({
      address: 'http://localhost:8001',
      page: null,
    })
  })
  it('refuses a user name or password in the address', () => {
    expect(parseHubAddress('https://hub.example@evil.example/a/b')).toBeNull()
    expect(parseHubAddress('https://u:p@hub.example/a/b')).toBeNull()
  })
  it('gives the host to show', () => {
    expect(parseHubAddress('https://hub.civex.uk.evil.com/a/b')?.host).toBe(
      'hub.civex.uk.evil.com',
    )
  })
  it('refuses what is not a web address', () => {
    expect(parseHubAddress('')).toBeNull()
    expect(parseHubAddress('ssh://me@box/~/p')).toBeNull()
  })
})

describe('approvalUrl', () => {
  const hub = 'https://hub.example/ada/notes/data'
  it('fills the code in once', () => {
    expect(approvalUrl('https://hub.example/a/b/device', 'AB-12', hub)).toBe(
      'https://hub.example/a/b/device?code=AB-12',
    )
    expect(
      approvalUrl('https://hub.example/a/b/device?code=AB-12', 'AB-12', hub),
    ).toBe('https://hub.example/a/b/device?code=AB-12')
  })
  it('never uses a page that is not on the hub', () => {
    for (const bad of [
      'javascript:alert(1)',
      'data:text/html,hi',
      'https://evil.example/device',
      'https://hub.example.evil.example/device',
      'https://u@hub.example/device',
      'http://hub.example/device',
      '/a/b/device',
      'device',
      '',
      null,
    ])
      expect(approvalUrl(bad, 'AB-12', hub)).toBeNull()
  })
})
