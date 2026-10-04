import { describe, it, expect, afterEach } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { Page } from './Page'

afterEach(() => {
  document.title = 'civex'
})

const renderPage = (ui: React.ReactNode) =>
  render(<MemoryRouter>{ui}</MemoryRouter>)

describe('Page sets the browser tab title', () => {
  it('from a text title', () => {
    renderPage(<Page title="Runs" />)
    expect(document.title).toBe('Runs · civex')
  })

  it("from the trail when the title is a node: a record's name, then where it is", () => {
    renderPage(
      <Page
        breadcrumbs={[
          { label: 'study', to: '/collections/1' },
          { label: 'Patient 3', to: '/records/p' },
          { label: 'Visit 1' },
        ]}
        title={<span>Visit 1 and a badge</span>}
      />,
    )
    expect(document.title).toBe('Visit 1 · Patient 3 · study · civex')
  })

  it('uses a text title with the trail for context, not the trail end', () => {
    renderPage(
      <Page
        breadcrumbs={[{ label: 'Runs', to: '/runs' }, { label: 'a1b2c3d4…' }]}
        title="compute"
      />,
    )
    expect(document.title).toBe('compute · Runs · civex')
  })

  it('takes an explicit title for a page made of several areas', () => {
    renderPage(
      <Page
        title="Settings"
        documentTitle={['Tasks', 'Storage', 'Settings']}
      />,
    )
    expect(document.title).toBe('Tasks · Storage · Settings · civex')
  })

  it('follows the page as it changes', () => {
    const { rerender } = renderPage(<Page title="Runs" />)
    rerender(
      <MemoryRouter>
        <Page title="Collections" />
      </MemoryRouter>,
    )
    expect(document.title).toBe('Collections · civex')
  })

  it('goes back to the app name when the page goes away', () => {
    const { unmount } = renderPage(<Page title="Runs" />)
    expect(document.title).toBe('Runs · civex')
    unmount()
    expect(document.title).toBe('civex')
  })
})
