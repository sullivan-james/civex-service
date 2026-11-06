import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { FileCell } from './FileCell'

const ref = (filename: string, size = 2048) => ({
  sha256: filename.padEnd(64, '0'),
  filename,
  size,
})

describe('FileCell', () => {
  it('shows a file by name and size, not as JSON', () => {
    const { container } = render(<FileCell value={ref('a.wav')} />)
    expect(screen.getByText('a.wav').closest('a')).not.toBeNull()
    expect(screen.getByText('2.0 KB')).toBeInTheDocument()
    expect(container.textContent).not.toContain('sha256')
  })

  it('shows the first of a list and how many more, every name on hover', () => {
    const { container } = render(
      <FileCell value={[ref('a.wav'), ref('b.wav'), ref('c.wav')]} />,
    )
    expect(screen.getByText('a.wav')).toBeInTheDocument()
    expect(screen.getByText('+2 more')).toBeInTheDocument()
    const hover = container.firstElementChild?.getAttribute('title') ?? ''
    expect(hover).toMatch(/^3 files/)
    expect(hover).toContain('c.wav')
  })

  it('prefers the name the field gives the file', () => {
    render(
      <FileCell
        value={{ ...ref('upload.wav'), resolved_filename: 'S1.wav' }}
      />,
    )
    expect(screen.getByText('S1.wav')).toBeInTheDocument()
  })

  it('is a dash when there are no files', () => {
    render(<FileCell value={[]} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})
