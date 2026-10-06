import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { saveReview } from '../../utils/reviewSession'
import { ReviewStepper } from './ReviewStepper'

function open(ids: string[]) {
  return ids.map((id) => ({
    id: `c-${id}`,
    entity_id: id,
    entity_type: 'record',
    record_name: `Rec ${id}`,
    kind: 'conflict',
    created_at: '2026-10-05T10:00:00Z',
  }))
}

function show(openIds: string[], recordId: string, active = false) {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify(open(openIds)), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    ),
  )
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ReviewStepper recordId={recordId} active={active} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => sessionStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('ReviewStepper', () => {
  it('is not there when no review has started and the Resolve tab is not open', async () => {
    show(['a', 'b'], 'a')
    await new Promise((r) => setTimeout(r, 30))
    expect(screen.queryByRole('navigation')).toBeNull()
  })

  it('asks for nothing while no review is going and the Resolve tab is not open', async () => {
    show(['a'], 'a')
    await new Promise((r) => setTimeout(r, 30))
    expect(vi.mocked(fetch)).not.toHaveBeenCalled()
  })

  it('starts one on the Resolve tab, with every record that has something to settle as a step', async () => {
    show(['a', 'b', 'c'], 'b', true)
    expect(await screen.findByLabelText('Review progress')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Rec b, step 2 of 3' }),
    ).toHaveAttribute('aria-current', 'step')
    expect(screen.getByText('3 of 3 left')).toBeInTheDocument()
  })

  it('ticks off a record with nothing left, and goes on to the next that has', async () => {
    saveReview([
      { id: 'a', name: 'Rec a' },
      { id: 'b', name: 'Rec b' },
      { id: 'c', name: 'Rec c' },
    ])
    show(['b', 'c'], 'b')
    expect(
      await screen.findByRole('link', { name: 'Rec a, step 1 of 3, settled' }),
    ).toBeInTheDocument()
    expect(screen.getByText('2 of 3 left')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Next: Rec c' })).toHaveAttribute(
      'href',
      '/records/c?tab=resolve',
    )
  })

  it('says when everything is settled and offers to finish', async () => {
    saveReview([{ id: 'a', name: 'Rec a' }])
    show([], 'a')
    expect(await screen.findByText('All settled')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Finish' })).toBeInTheDocument()
  })
})
