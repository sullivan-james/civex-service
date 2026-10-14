import { afterEach, describe, expect, it, vi } from 'vitest'
import * as React from 'react'
import { loadExtensions } from './extensions'
import { clearSlots, slotEntries } from './slots'

afterEach(() => {
  clearSlots()
  delete window.__CIVEX__
})

describe('extensions', () => {
  it('are handed the app’s React and a register, and draw into slots', async () => {
    window.__CIVEX__ = { extensions: ['/ext/hub.js'] }
    const load = vi.fn(async () => {
      const civex = window.__CIVEX__ as unknown as {
        register: (slot: string, c: () => null, o: object) => void
        shared: Record<string, unknown>
      }
      const shared = civex.shared.react as typeof React
      expect(shared.useState).toBe(React.useState)
      civex.register('workflow.actions', () => null, { id: 'run-on-hub' })
    })
    await loadExtensions(undefined, load)
    expect(load).toHaveBeenCalledWith('/ext/hub.js')
    expect(slotEntries('workflow.actions').map((e) => e.id)).toEqual([
      'run-on-hub',
    ])
    // What the page said stays.
    expect(window.__CIVEX__?.extensions).toEqual(['/ext/hub.js'])
  })

  it('that fail to load cost only themselves', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {})
    await expect(
      loadExtensions(['/a.js', '/b.js'], async (url) => {
        if (url === '/a.js') throw new Error('404')
      }),
    ).resolves.toBeUndefined()
    expect(error).toHaveBeenCalledOnce()
    error.mockRestore()
  })

  it('are none on a local civex', async () => {
    const load = vi.fn()
    await loadExtensions(undefined, load)
    expect(load).not.toHaveBeenCalled()
  })
})
