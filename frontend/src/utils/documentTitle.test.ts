import { describe, it, expect } from 'vitest'
import { APP_NAME, formatTitle, pageTitleParts } from './documentTitle'

describe('formatTitle', () => {
  it('puts the specific part first and the app name last', () => {
    expect(formatTitle(['Sample 12', 'study'])).toBe(
      'Sample 12 · study · civex',
    )
  })

  it('is just the app name when there is nothing to say', () => {
    expect(formatTitle([])).toBe(APP_NAME)
    expect(formatTitle(['', null, undefined, false, '  '])).toBe(APP_NAME)
  })

  it('leaves out empty parts and a name repeated in a row', () => {
    expect(formatTitle(['', 'Storage', 'Storage', 'Settings'])).toBe(
      'Storage · Settings · civex',
    )
  })

  it('keeps the first three parts, so a deep page does not fill the tab', () => {
    expect(formatTitle(['a', 'b', 'c', 'd', 'e'])).toBe('a · b · c · civex')
  })

  it('clips a very long name', () => {
    const title = formatTitle(['x'.repeat(100)])
    expect(title.endsWith('… · civex')).toBe(true)
    expect(title.length).toBeLessThan(60)
  })
})

describe('pageTitleParts', () => {
  it('is the title for a page with no trail', () => {
    expect(pageTitleParts('Runs', undefined)).toEqual(['Runs'])
  })

  it('is the current item then what it sits inside, nearest first', () => {
    const trail = [
      { label: 'study' },
      { label: 'Patient 3' },
      { label: 'Visit 1' },
    ]
    // The title here is a node (name plus a badge), so the trail names the page.
    expect(pageTitleParts({}, trail)).toEqual(['Visit 1', 'Patient 3', 'study'])
  })

  it('uses a text title for the page and the trail for the rest, never the id fragment', () => {
    const trail = [{ label: 'Runs' }, { label: 'a1b2c3d4…' }]
    expect(pageTitleParts('compute', trail)).toEqual(['compute', 'Runs'])
  })

  it('is empty when nothing says what the page is', () => {
    expect(pageTitleParts({}, undefined)).toEqual([])
  })
})
