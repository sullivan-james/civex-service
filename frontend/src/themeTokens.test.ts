import { describe, it, expect } from 'vitest'

const sources = import.meta.glob('./**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

describe('dark mode', () => {
  it('uses theme tokens, never a hard-coded white background', () => {
    // `bg-white` doesn't change in dark mode, so light text (text-fg) ends up on
    // white. Surfaces take bg-canvas / bg-canvas-subtle, which both themes define.
    const offenders = Object.entries(sources)
      .filter(([file]) => !/\.test\.tsx?$/.test(file))
      .filter(([, source]) => /\bbg-white\b/.test(source))
      .map(([file]) => file)

    expect(offenders).toEqual([])
  })
})
