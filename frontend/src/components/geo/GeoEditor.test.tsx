import { describe, it, expect, vi } from 'vitest'
import {
  render,
  screen,
  fireEvent,
  within,
  waitFor,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { GeoEditor } from './GeoEditor'
import type { Geometry } from '../../utils/geo'

// The map itself (OpenLayers on a canvas) can't run in jsdom: stand in for it
// with buttons that report the same edits a mouse would.
vi.mock('./GeoMap', () => ({
  default: (p: {
    draft: { shape: string; positions: number[][] }
    drawing: boolean
    onChange: (p: number[][]) => void
    onDrawEnd: () => void
    bbox: number[] | null
  }) => (
    <div
      data-testid="map"
      data-shape={p.draft.shape}
      data-drawing={String(p.drawing)}
      data-bbox={JSON.stringify(p.bbox)}
    >
      <button type="button" onClick={() => p.onChange([[-3.41, 56.12]])}>
        map click
      </button>
      <button
        type="button"
        onClick={() => {
          p.onChange([
            [0, 0],
            [0, 1],
            [1, 1],
          ])
          p.onDrawEnd()
        }}
      >
        map draw
      </button>
    </div>
  ),
}))

const POINT: Geometry = { type: 'Point', coordinates: [-3.41, 56.12] }

function setup(value: Geometry | null, rules = {}) {
  const onApply = vi.fn()
  const onCancel = vi.fn()
  render(
    <GeoEditor
      value={value}
      rules={rules}
      onApply={onApply}
      onCancel={onCancel}
    />,
  )
  return { onApply, onCancel }
}

describe('point editing', () => {
  it('shows an existing point as latitude and longitude with hemispheres', async () => {
    setup(POINT)
    await screen.findByTestId('map')
    expect(screen.getByLabelText('Latitude degrees')).toHaveValue('56.12')
    expect(screen.getByLabelText('Latitude hemisphere')).toHaveValue('N')
    expect(screen.getByLabelText('Longitude degrees')).toHaveValue('3.41')
    expect(screen.getByLabelText('Longitude hemisphere')).toHaveValue('W')
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled()
  })

  it('takes a position clicked on the map', async () => {
    const { onApply } = setup(null)
    await userEvent.click(
      await screen.findByRole('button', { name: 'map click' }),
    )
    expect(screen.getByLabelText('Latitude degrees')).toHaveValue('56.12')
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onApply).toHaveBeenCalledWith({
      type: 'Point',
      coordinates: [-3.41, 56.12],
    })
  })

  it('reads pasted coordinates in other formats', async () => {
    const { onApply } = setup(null)
    await screen.findByTestId('map')
    await userEvent.type(
      screen.getByLabelText('Or paste coordinates'),
      `56°07'12"N 3°24'36"W`,
    )
    expect(screen.getByLabelText('Latitude degrees')).toHaveValue('56.12')
    expect(screen.getByLabelText('Longitude hemisphere')).toHaveValue('W')
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    const g = onApply.mock.calls[0][0]
    expect(g.coordinates[0]).toBeCloseTo(-3.41, 6)
    expect(g.coordinates[1]).toBeCloseTo(56.12, 6)
  })

  it('shows the same position as degrees, minutes and seconds', async () => {
    setup(POINT)
    await screen.findByTestId('map')
    await userEvent.selectOptions(
      screen.getByLabelText('Coordinates as'),
      'dms',
    )
    expect(screen.getByLabelText('Latitude degrees')).toHaveValue('56')
    expect(screen.getByLabelText('Latitude minutes')).toHaveValue('7')
    expect(screen.getByLabelText('Latitude seconds')).toHaveValue('12')
    expect(screen.getByLabelText('Longitude minutes')).toHaveValue('24')
  })

  it('moves to the other hemisphere without a minus sign', async () => {
    const { onApply } = setup(POINT)
    await screen.findByTestId('map')
    await userEvent.selectOptions(
      screen.getByLabelText('Latitude hemisphere'),
      'S',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onApply).toHaveBeenCalledWith({
      type: 'Point',
      coordinates: [-3.41, -56.12],
    })
  })

  it('refuses a sign typed into a magnitude box', async () => {
    setup(null)
    await screen.findByTestId('map')
    await userEvent.type(screen.getByLabelText('Latitude degrees'), '-5')
    expect(screen.getByText(/without a sign/)).toBeInTheDocument()
  })

  it('keeps elevation and uncertainty', async () => {
    const { onApply } = setup(POINT)
    await screen.findByTestId('map')
    await userEvent.type(screen.getByLabelText(/Elevation/), '-300')
    await userEvent.type(screen.getByLabelText(/Uncertainty/), '120')
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onApply).toHaveBeenCalledWith({
      type: 'Point',
      coordinates: [-3.41, 56.12, -300],
      uncertainty_m: 120,
    })
  })
})

describe('field rules', () => {
  it('blocks applying a point outside the allowed area and passes the area to the map', async () => {
    setup(null, { bbox: [-12, 48, 4, 62] })
    const map = await screen.findByTestId('map')
    expect(map).toHaveAttribute('data-bbox', '[-12,48,4,62]')
    await userEvent.type(
      screen.getByLabelText('Or paste coordinates'),
      '63.4, -20.1',
    )
    expect(screen.getByRole('alert')).toHaveTextContent(
      /outside the allowed area/,
    )
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled()
  })

  it('offers only the shapes the field accepts', async () => {
    setup(null, { geometry_types: ['Point', 'Polygon'] })
    await screen.findByTestId('map')
    const tabs = screen.getAllByRole('tab').map((t) => t.textContent)
    expect(tabs).toEqual(['Point', 'Area'])
  })

  it('has no shape tabs when only one shape is allowed', async () => {
    setup(null, { geometry_types: ['Polygon'] })
    const map = await screen.findByTestId('map')
    expect(screen.queryAllByRole('tab')).toHaveLength(0)
    expect(map).toHaveAttribute('data-shape', 'Polygon')
    expect(map).toHaveAttribute('data-drawing', 'true')
  })

  it('says when a field only takes shapes it cannot draw', () => {
    setup(null, { geometry_types: ['MultiPolygon'] })
    expect(screen.getByText(/can’t draw/)).toBeInTheDocument()
  })
})

describe('lines and areas', () => {
  it('lists the vertices, measures, and applies a closed ring', async () => {
    const { onApply } = setup(null, { geometry_types: ['Polygon'] })
    await userEvent.click(
      await screen.findByRole('button', { name: 'map draw' }),
    )
    expect(screen.getByLabelText('corner 1 latitude')).toHaveValue('0')
    expect(screen.getByText(/3 corners/)).toBeInTheDocument()
    expect(screen.getByText(/Area:/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onApply.mock.calls[0][0]).toEqual({
      type: 'Polygon',
      coordinates: [
        [
          [0, 0],
          [0, 1],
          [1, 1],
          [0, 0],
        ],
      ],
    })
  })

  it('edits and removes vertices from the table', async () => {
    const { onApply } = setup(null, { geometry_types: ['LineString'] })
    await userEvent.click(
      await screen.findByRole('button', { name: 'map draw' }),
    )
    const lat = screen.getByLabelText('point 2 latitude')
    await userEvent.clear(lat)
    await userEvent.type(lat, '5')
    fireEvent.blur(lat)
    await userEvent.click(screen.getByLabelText('Remove point 3'))
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onApply.mock.calls[0][0]).toEqual({
      type: 'LineString',
      coordinates: [
        [0, 0],
        [0, 5],
      ],
    })
  })

  it('says what a short line is missing', async () => {
    setup(null, { geometry_types: ['LineString'] })
    await screen.findByTestId('map')
    await userEvent.click(screen.getByRole('button', { name: '+ Add point' }))
    expect(screen.getByRole('alert')).toHaveTextContent(/at least 2/)
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled()
  })

  it('warns about a shape it cannot edit instead of dropping it', async () => {
    setup({
      type: 'MultiPoint',
      coordinates: [
        [0, 0],
        [1, 1],
      ],
    })
    await screen.findByTestId('map')
    expect(screen.getByRole('status')).toHaveTextContent(
      /can’t change a MultiPoint/,
    )
  })
})

describe('import', () => {
  const upload = (file: File) => {
    const input = screen.getByLabelText(
      'Import a location file',
    ) as HTMLInputElement
    return userEvent.upload(input, file)
  }

  it('fills the editor from a GeoJSON file', async () => {
    const { onApply } = setup(null)
    await screen.findByTestId('map')
    const gj = {
      type: 'Feature',
      properties: {},
      geometry: { type: 'Point', coordinates: [-3.41, 56.12] },
    }
    await upload(
      new File([JSON.stringify(gj)], 'site.geojson', {
        type: 'application/json',
      }),
    )
    await waitFor(() =>
      expect(screen.getByLabelText('Latitude degrees')).toHaveValue('56.12'),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onApply).toHaveBeenCalledWith({
      type: 'Point',
      coordinates: [-3.41, 56.12],
    })
  })

  it('lets you pick one location out of several', async () => {
    setup(null, { geometry_types: ['Point'] })
    await screen.findByTestId('map')
    const fc = {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: { name: 'North' },
          geometry: { type: 'Point', coordinates: [1, 2] },
        },
        {
          type: 'Feature',
          properties: { name: 'South' },
          geometry: { type: 'Point', coordinates: [3, -4] },
        },
      ],
    }
    await upload(new File([JSON.stringify(fc)], 'sites.json'))
    const list = await screen.findByRole('list', {
      name: 'Locations in the file',
    })
    await userEvent.click(within(list).getByRole('button', { name: 'South' }))
    expect(screen.getByLabelText('Latitude degrees')).toHaveValue('4')
    expect(screen.getByLabelText('Latitude hemisphere')).toHaveValue('S')
  })

  it('reads a GPS track as one line', async () => {
    setup(null, { geometry_types: ['LineString'] })
    await screen.findByTestId('map')
    const gpx = `<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">
      <trk><name>Dive 1</name><trkseg>
        <trkpt lat="56.0" lon="-3.0"/><trkpt lat="56.1" lon="-3.1"/></trkseg>
        <trkseg><trkpt lat="56.2" lon="-3.2"/></trkseg></trk></gpx>`
    await upload(new File([gpx], 'dive.gpx'))
    expect(await screen.findByLabelText('point 3 latitude')).toHaveValue('56.2')
    expect(screen.getByText(/3 points/)).toBeInTheDocument()
  })

  it('explains a file with the wrong shape for the field', async () => {
    setup(null, { geometry_types: ['Polygon'] })
    await screen.findByTestId('map')
    const gj = { type: 'Point', coordinates: [1, 2] }
    await upload(new File([JSON.stringify(gj)], 'p.geojson'))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /this field takes area/,
    )
  })
})
