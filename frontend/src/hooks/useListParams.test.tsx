import { describe, it, expect } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { useListParams } from './useListParams'

const wrap = (url: string) =>
  function Wrap({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={[url]}>{children}</MemoryRouter>
  }

describe('useListParams', () => {
  it('reads dropdowns, search, sort and page from the address', () => {
    const { result } = renderHook(() => useListParams('', ['status']), {
      wrapper: wrap('/runs?status=failed&q=parse&sort=created_at:desc&page=3'),
    })
    expect(result.current.picks.status).toBe('failed')
    expect(result.current.q).toBe('parse')
    expect(result.current.sortParam).toBe('created_at:desc')
    expect(result.current.page).toBe(2)
  })

  it('goes back to page one when something else changes, and keeps ns apart', () => {
    const { result } = renderHook(() => useListParams('runs.', ['status']), {
      wrapper: wrap('/r?runs.page=4&history.q=x'),
    })
    act(() => result.current.set({ status: 'failed' }))
    expect(result.current.picks.status).toBe('failed')
    expect(result.current.page).toBe(0)
  })

  it('cycles a column ascending, descending, off', () => {
    const { result } = renderHook(() => useListParams('', []), {
      wrapper: wrap('/runs'),
    })
    act(() => result.current.toggleSort('status'))
    expect(result.current.sortParam).toBe('status:asc')
    act(() => result.current.toggleSort('status'))
    expect(result.current.sortParam).toBe('status:desc')
    act(() => result.current.toggleSort('status'))
    expect(result.current.sortParam).toBeUndefined()
  })
})
