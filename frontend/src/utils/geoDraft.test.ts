import { describe, expect, it } from 'vitest'
import {
  draftFromGeometry,
  editableShapes,
  emptyDraft,
  geometryFromDraft,
} from './geoDraft'

describe('editable shapes', () => {
  it('offers every drawable shape unless the field limits them', () => {
    expect(editableShapes({})).toEqual(['Point', 'LineString', 'Polygon'])
    expect(editableShapes({ geometry_types: ['Point', 'Polygon'] })).toEqual([
      'Point',
      'Polygon',
    ])
    expect(editableShapes({ geometry_types: ['MultiPolygon'] })).toEqual([])
  })
})

describe('draft <-> GeoJSON', () => {
  it('round-trips a point with depth and uncertainty', () => {
    const g = {
      type: 'Point',
      coordinates: [-3.41, 56.12, -300],
      uncertainty_m: 120,
    }
    const { draft } = draftFromGeometry(g, 'Point')
    expect(draft).toMatchObject({
      shape: 'Point',
      positions: [[-3.41, 56.12]],
      elevation: -300,
      uncertainty: 120,
    })
    expect(geometryFromDraft(draft).geometry).toEqual(g)
  })

  it('leaves optional point parts out when unset', () => {
    const d = {
      ...emptyDraft('Point'),
      positions: [[1, 2]] as [number, number][],
    }
    expect(geometryFromDraft(d).geometry).toEqual({
      type: 'Point',
      coordinates: [1, 2],
    })
  })

  it('closes an area ring and opens it again for editing', () => {
    const d = {
      ...emptyDraft('Polygon'),
      positions: [
        [0, 0],
        [0, 1],
        [1, 1],
      ] as [number, number][],
    }
    const g = geometryFromDraft(d).geometry!
    expect(g.coordinates).toEqual([
      [
        [0, 0],
        [0, 1],
        [1, 1],
        [0, 0],
      ],
    ])
    expect(draftFromGeometry(g, 'Polygon').draft.positions).toEqual(d.positions)
  })

  it('says what is missing', () => {
    expect(
      geometryFromDraft({ ...emptyDraft('LineString'), positions: [[0, 0]] })
        .problem,
    ).toMatch(/at least 2/)
    expect(
      geometryFromDraft({
        ...emptyDraft('Polygon'),
        positions: [
          [0, 0],
          [1, 1],
        ],
      }).problem,
    ).toMatch(/at least 3/)
    expect(geometryFromDraft(emptyDraft('Point'))).toEqual({
      geometry: null,
      problem: null,
    })
  })

  it('wraps longitudes that ran past the date line', () => {
    const d = {
      ...emptyDraft('Point'),
      positions: [[190, 10]] as [number, number][],
    }
    expect(geometryFromDraft(d).geometry?.coordinates).toEqual([-170, 10])
  })

  it('refuses to edit what it cannot represent', () => {
    expect(
      draftFromGeometry({ type: 'MultiPoint', coordinates: [[0, 0]] }, 'Point')
        .unsupported,
    ).toMatch(/MultiPoint/)
    const holey = {
      type: 'Polygon',
      coordinates: [
        [
          [0, 0],
          [0, 9],
          [9, 9],
          [0, 0],
        ],
        [
          [1, 1],
          [1, 2],
          [2, 2],
          [1, 1],
        ],
      ],
    }
    expect(draftFromGeometry(holey, 'Polygon').unsupported).toMatch(/holes/)
  })
})
