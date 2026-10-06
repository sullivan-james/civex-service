import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SavedViewBar } from './SavedViewBar'
import type { FilesLayout, View } from '../../api/views'

const view = (layout: FilesLayout): View => ({
  id: 'v1',
  schema_id: 's',
  schema_name: 'selection',
  name: 'Tables',
  columns: ['selection_table'],
  filter_tree: null,
  sort: [],
  files_layout: layout,
})

function renderIt(
  layout: FilesLayout | undefined,
  onFilesLayout?: (l: FilesLayout) => void,
) {
  const active = view(layout ?? 'tree')
  render(
    <SavedViewBar
      views={[active]}
      activeView={active}
      modified={false}
      hasSelection
      onApply={() => {}}
      onClear={() => {}}
      onSave={() => {}}
      onSaveAs={() => {}}
      onRename={() => {}}
      onDelete={() => {}}
      filesLayout={layout}
      onFilesLayout={onFilesLayout}
      pending={false}
      error={null}
    />,
  )
}

const openMenu = () =>
  userEvent.click(screen.getByRole('button', { name: /manage view tables/i }))

describe('a saved view’s files layout', () => {
  it('offers the other two layouts to a view that arranges files by record', async () => {
    const choose = vi.fn()
    renderIt('tree', choose)
    await openMenu()

    expect(
      screen.queryByRole('menuitem', {
        name: /export files: a folder per record/i,
      }),
    ).toBeNull()
    await userEvent.click(
      screen.getByRole('menuitem', {
        name: /export files: all in one folder/i,
      }),
    )

    expect(choose).toHaveBeenCalledWith('flat')
  })

  it('offers grouping by kind', async () => {
    const choose = vi.fn()
    renderIt('tree', choose)
    await openMenu()

    await userEvent.click(
      screen.getByRole('menuitem', { name: /export files: grouped by kind/i }),
    )

    expect(choose).toHaveBeenCalledWith('grouped')
  })

  it('offers the way back for a flat one', async () => {
    const choose = vi.fn()
    renderIt('flat', choose)
    await openMenu()

    await userEvent.click(
      screen.getByRole('menuitem', {
        name: /export files: a folder per record/i,
      }),
    )

    expect(choose).toHaveBeenCalledWith('tree')
  })

  it('says nothing about files where the records have none', async () => {
    renderIt(undefined, undefined)
    await openMenu()

    expect(screen.queryByRole('menuitem', { name: /export files/i })).toBeNull()
    expect(screen.getByRole('menuitem', { name: /rename view/i })).toBeTruthy()
  })
})
