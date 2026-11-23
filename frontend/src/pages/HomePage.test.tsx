import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import HomePage from './HomePage'
import { localFeatures } from '../utils/features'

let features: ReadonlySet<string> = localFeatures
let collections: unknown[] = []
const jobs = vi.fn(() => ({ jobs: { data: [] } }))

vi.mock('../hooks/useFeatures', () => ({ useFeatures: () => features }))
vi.mock('../hooks/useCollections', () => ({
  useCollections: () => ({ data: collections }),
}))
vi.mock('../hooks/useWorkflows', () => ({ useJobsPaged: () => jobs() }))
vi.mock('../components/home/HomeShortcuts', () => ({
  HomeShortcuts: () => null,
}))
vi.mock('../components/settings/DesktopShortcut', () => ({
  DesktopShortcut: () => null,
}))

function renderHome() {
  render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  )
}

describe('HomePage', () => {
  it('offers every step and the recent runs on a local, empty project', () => {
    features = localFeatures
    collections = []
    renderHome()
    expect(screen.getByText('Start a collection')).toBeInTheDocument()
    expect(screen.getByText('Automate the rest')).toBeInTheDocument()
    expect(screen.getByText('Recent activity')).toBeInTheDocument()
  })

  it('drops workflow steps and runs on a host without workflows', () => {
    features = new Set(['ai'])
    collections = []
    jobs.mockClear()
    renderHome()
    expect(screen.getByText('Add records')).toBeInTheDocument()
    expect(screen.queryByText('Automate the rest')).toBeNull()
    expect(screen.queryByText('Recent activity')).toBeNull()
    expect(jobs).not.toHaveBeenCalled()
  })

  it('does not onboard a project that already has collections', () => {
    features = localFeatures
    collections = [{ id: 'c1', name: 'survey', record_count: 72000 }]
    renderHome()
    expect(screen.getByText('survey')).toBeInTheDocument()
    expect(screen.getByText('72,000 records')).toBeInTheDocument()
    expect(screen.queryByText('Start a collection')).toBeNull()
  })
})
