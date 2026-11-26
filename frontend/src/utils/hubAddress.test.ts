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
  it('refuses what is not a web address', () => {
    expect(parseHubAddress('')).toBeNull()
    expect(parseHubAddress('ssh://me@box/~/p')).toBeNull()
  })
})

describe('approvalUrl', () => {
  it('fills the code in once', () => {
    expect(approvalUrl('https://h/a/b/device', 'AB-12')).toBe(
      'https://h/a/b/device?code=AB-12',
    )
    expect(approvalUrl('https://h/a/b/device?code=AB-12', 'AB-12')).toBe(
      'https://h/a/b/device?code=AB-12',
    )
  })
})
