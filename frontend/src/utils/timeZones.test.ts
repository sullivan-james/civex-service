import { describe, it, expect } from 'vitest'
import { timeZoneOptions } from './timeZones'

describe('timeZoneOptions', () => {
  it('lists UTC first, then zones alphabetically', () => {
    const options = timeZoneOptions()
    expect(options[0]).toBe('UTC')
    expect(options).toContain('America/Chicago')
    expect(options.slice(1)).toEqual(
      [...options.slice(1)].sort((a, b) => a.localeCompare(b)),
    )
  })

  it('always includes the saved zone, but never an unknown one', () => {
    expect(timeZoneOptions('Asia/Kolkata')).toContain('Asia/Kolkata')
    expect(timeZoneOptions('Mars/Olympus')).not.toContain('Mars/Olympus')
  })
})
