import { describe, it, expect, vi, afterEach } from 'vitest'
import { restartForUpdate } from './updateRestart'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('restartForUpdate', () => {
  it('reloads only once civex has gone away and come back', async () => {
    vi.useFakeTimers()
    // Still up just after answering, then gone, then back.
    const health = [true, false, false, true]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url === '/api/update')
          return new Response(JSON.stringify({ restarting: true }), {
            status: 202,
            headers: { 'Content-Type': 'application/json' },
          })
        return new Response('{}', { status: health.shift() ? 200 : 503 })
      }),
    )
    const reload = vi.fn()
    vi.stubGlobal('location', { ...window.location, reload })

    const done = restartForUpdate({ pre: false })
    for (let i = 0; i < 5; i++) await vi.advanceTimersByTimeAsync(1000)
    await done
    expect(reload).toHaveBeenCalledTimes(1)
    expect(health).toEqual([])
  })
})
