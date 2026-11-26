import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import type { Collection } from '../../api/collections'
import { EmptyCollectionGuide } from './EmptyCollectionGuide'

const collection = { id: 'c1', name: 'study' } as Collection

function show(importHref?: string) {
  render(
    <MemoryRouter>
      <EmptyCollectionGuide
        collection={collection}
        schemas={[]}
        newMenu={null}
        importHref={importHref}
      />
    </MemoryRouter>,
  )
}

describe('EmptyCollectionGuide', () => {
  it('offers to import a spreadsheet where records can be brought in', () => {
    show('/collections/c1/import')
    expect(
      screen.getByRole('link', { name: 'Import spreadsheet' }),
    ).toHaveAttribute('href', '/collections/c1/import')
  })

  it('does not where they cannot', () => {
    show()
    expect(screen.queryByText('Import spreadsheet')).toBeNull()
  })
})
