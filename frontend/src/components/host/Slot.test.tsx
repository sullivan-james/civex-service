import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { Slot, SlotItem } from './Slot'
import { clearSlots, register, slotEntries } from '../../utils/slots'

afterEach(() => clearSlots())

describe('slots', () => {
  it('draw nothing until an extension registers, then what it gave, with the slot’s props', () => {
    const { container } = render(
      <Slot name="record.header" props={{ recordId: 'r1' }} />,
    )
    expect(container).toBeEmptyDOMElement()
    act(() => {
      register(
        'record.header',
        ({ recordId }: { recordId: string }) => (
          <span>Hub thing for {recordId}</span>
        ),
        { id: 'hub' },
      )
    })
    expect(screen.getByText('Hub thing for r1')).toBeInTheDocument()
  })

  it('refuse a name that isn’t a slot, so a misspelling fails loudly', () => {
    expect(() => register('record.heder', () => null)).toThrow(
      /no slot "record.heder"/,
    )
  })

  it('replace an entry registered again under the same id, and can take it out', () => {
    const one = () => <span>one</span>
    const two = () => <span>two</span>
    register('storage.summary', one, { id: 'meter' })
    const remove = register('storage.summary', two, { id: 'meter' })
    expect(slotEntries('storage.summary').map((e) => e.Component)).toEqual([
      two,
    ])
    remove()
    expect(slotEntries('storage.summary')).toEqual([])
  })

  it('keep a page standing when an extension’s component fails', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {})
    register(
      'collection.header',
      () => {
        throw new Error('broken')
      },
      { id: 'broken' },
    )
    register('collection.header', () => <span>still here</span>, { id: 'ok' })
    render(<Slot name="collection.header" props={{ collectionId: 'c' }} />)
    expect(screen.getByText('still here')).toBeInTheDocument()
    error.mockRestore()
  })

  it('draw one entry by id, or the fallback while there is none', () => {
    render(
      <SlotItem name="settings.sections" id="billing" fallback={<p>none</p>} />,
    )
    expect(screen.getByText('none')).toBeInTheDocument()
    act(() => {
      register('settings.sections', () => <p>Billing</p>, {
        id: 'billing',
        label: 'Billing',
      })
    })
    expect(screen.getByText('Billing')).toBeInTheDocument()
  })
})
