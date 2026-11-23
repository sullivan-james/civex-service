import { describe, expect, it } from 'vitest'
import { localFeatures, offered } from './features'

describe('offered', () => {
  it('applies to everything a local civex does until the server says less', () => {
    expect(offered(localFeatures, { feature: 'volumes' })).toBe(true)
    expect(offered(localFeatures, { feature: 'terminal' })).toBe(true)
  })

  it('hides what a narrower server does not do', () => {
    const hosted = new Set(['ai'])
    expect(offered(hosted, { feature: 'volumes' })).toBe(false)
    expect(offered(hosted, { feature: 'ai' })).toBe(true)
  })

  it('always applies to an item that names no feature', () => {
    expect(offered(new Set(), {})).toBe(true)
  })

  it('counts every settings section as off when the settings umbrella is', () => {
    const noUmbrella = new Set(['settings_map', 'settings_devices', 'terminal'])
    expect(offered(noUmbrella, { feature: 'settings_map' })).toBe(false)
    expect(
      offered(noUmbrella, { feature: ['accounts', 'settings_members'] }),
    ).toBe(false)
    expect(offered(noUmbrella, { feature: 'terminal' })).toBe(true)
    const withUmbrella = new Set(['settings', 'settings_map'])
    expect(offered(withUmbrella, { feature: 'settings_map' })).toBe(true)
    expect(offered(withUmbrella, { feature: 'settings_retention' })).toBe(false)
  })
})
