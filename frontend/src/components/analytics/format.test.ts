import { describe, it, expect } from 'vitest'
import { formatDurationSeconds, formatCompactNumber, formatBytes } from './format'

describe('formatDurationSeconds', () => {
  it('formats sub-second durations as ms', () => {
    expect(formatDurationSeconds(0.25)).toBe('250ms')
  })

  it('formats seconds under a minute', () => {
    expect(formatDurationSeconds(5)).toBe('5.0s')
    expect(formatDurationSeconds(45)).toBe('45s')
  })

  it('formats minutes and hours', () => {
    expect(formatDurationSeconds(90)).toBe('1.5m')
    expect(formatDurationSeconds(7200)).toBe('2.0h')
  })
})

describe('formatCompactNumber', () => {
  it('leaves small numbers as-is', () => {
    expect(formatCompactNumber(42)).toBe('42')
    expect(formatCompactNumber(-7)).toBe('-7')
  })

  it('compacts thousands', () => {
    expect(formatCompactNumber(1500)).toBe('1.5k')
    expect(formatCompactNumber(42_000)).toBe('42k')
  })

  it('compacts millions', () => {
    expect(formatCompactNumber(2_500_000)).toBe('2.5M')
  })
})

describe('formatBytes', () => {
  it('leaves sub-KB counts as bytes', () => {
    expect(formatBytes(512)).toBe('512 B')
  })

  it('compacts KB/MB/GB', () => {
    expect(formatBytes(1536)).toBe('1.5 KB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB')
    expect(formatBytes(2.5 * 1024 * 1024 * 1024)).toBe('2.5 GB')
  })
})
