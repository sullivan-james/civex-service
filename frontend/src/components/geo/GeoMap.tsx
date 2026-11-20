import { useEffect, useRef } from 'react'
import type OlMap from 'ol/Map'
import Feature from 'ol/Feature'
import VectorLayer from 'ol/layer/Vector'
import VectorSource from 'ol/source/Vector'
import Draw from 'ol/interaction/Draw'
import Modify from 'ol/interaction/Modify'
import Snap from 'ol/interaction/Snap'
import { LineString, Point, Polygon } from 'ol/geom'
import { circular } from 'ol/geom/Polygon'
import { Circle as CircleStyle, Fill, Stroke, Style } from 'ol/style'
import { createBaseMap, themeColor as css, withAlpha } from './baseMap'
import type { Draft, Position } from '../../utils/geoDraft'
import { normalizeLon } from '../../utils/geoCoords'

/**
 * The map behind the location editor, on the shared base map (`baseMap`:
 * coastlines, graticule, optional tiles). It is controlled by the draft: edits on
 * the map are reported through `onChange`, and edits made elsewhere
 * (coordinate boxes, the vertex table) redraw it.
 */

export interface GeoMapProps {
  draft: Draft
  /** Allowed area [west, south, east, north]; west > east crosses 180°. */
  bbox: number[] | null
  /** Bump to re-frame the view (after an import, a clear, or opening). */
  fitKey: number
  /** True while a line or area is being drawn from scratch. */
  drawing: boolean
  onChange: (positions: Position[]) => void
  onDrawEnd: () => void
  onHover: (lon: number, lat: number) => void
  tileUrl?: string | null
  tileAttribution?: string | null
}

// 7 decimal places is about a centimetre: enough, and free of float noise.
const round = (n: number) => Math.round(n * 1e7) / 1e7

const toPositions = (coords: number[][]): Position[] =>
  coords.map(([lon, lat]) => [round(normalizeLon(lon)), round(lat)])

export default function GeoMap(props: GeoMapProps) {
  const host = useRef<HTMLDivElement>(null)
  const latest = useRef(props)
  // Handlers (set up once, below) read the newest props through this.
  useEffect(() => {
    latest.current = props
  })
  const parts = useRef<{
    map: OlMap
    draftSource: VectorSource
    areaSource: VectorSource
    drawSource: VectorSource
    draw: Draw | null
    quiet: boolean
  } | null>(null)

  // Build the map once.
  useEffect(() => {
    if (!host.current) return
    const accent = css('--color-accent', '#0969da')
    const danger = css('--color-danger', '#cf222e')

    const draftSource = new VectorSource()
    const areaSource = new VectorSource()
    const drawSource = new VectorSource()

    const draftStyle = (f: { getGeometry: () => unknown }) => {
      const g = f.getGeometry()
      if (g instanceof Polygon && (f as Feature).get('uncertainty'))
        return new Style({
          fill: new Fill({ color: withAlpha(danger, 0.13) }),
          stroke: new Stroke({ color: danger, width: 1, lineDash: [4, 4] }),
        })
      return new Style({
        stroke: new Stroke({ color: danger, width: 2.5 }),
        fill: new Fill({ color: withAlpha(danger, 0.13) }),
        image: new CircleStyle({
          radius: 6,
          fill: new Fill({ color: danger }),
          stroke: new Stroke({ color: '#fff', width: 2 }),
        }),
      })
    }

    const p = latest.current
    const map = createBaseMap(host.current, {
      tileUrl: p.tileUrl,
      tileAttribution: p.tileAttribution,
      overlays: [
        new VectorLayer({
          source: areaSource,
          style: new Style({
            fill: new Fill({ color: withAlpha(accent, 0.1) }),
            stroke: new Stroke({ color: accent, width: 2, lineDash: [8, 5] }),
          }),
        }),
        new VectorLayer({ source: draftSource, style: draftStyle as never }),
        new VectorLayer({
          source: drawSource,
          style: new Style({
            stroke: new Stroke({ color: danger, width: 2.5 }),
            fill: new Fill({ color: withAlpha(danger, 0.13) }),
          }),
        }),
      ],
    })
    parts.current = {
      map,
      draftSource,
      areaSource,
      drawSource,
      draw: null,
      quiet: false,
    }

    map.on('pointermove', (e) => {
      const [lon, lat] = e.coordinate
      latest.current.onHover(normalizeLon(lon), lat)
    })
    map.on('singleclick', (e) => {
      const cur = latest.current
      if (cur.draft.shape !== 'Point') return
      const [lon, lat] = e.coordinate
      cur.onChange(toPositions([[lon, lat]]))
    })

    const modify = new Modify({
      source: draftSource,
      style: new Style({
        image: new CircleStyle({
          radius: 7,
          fill: new Fill({ color: withAlpha(danger, 0.25) }),
          stroke: new Stroke({ color: danger, width: 2 }),
        }),
      }),
    })
    modify.on('modifyend', (e) => {
      const f = e.features.item(0) as Feature | undefined
      const g = f?.getGeometry()
      if (!g || !parts.current) return
      let coords: number[][] = []
      if (g instanceof Point) coords = [g.getCoordinates()]
      else if (g instanceof LineString) coords = g.getCoordinates()
      else if (g instanceof Polygon) coords = g.getCoordinates()[0].slice(0, -1)
      parts.current.quiet = true
      latest.current.onChange(toPositions(coords))
    })
    map.addInteraction(modify)
    map.addInteraction(new Snap({ source: draftSource }))

    const resize = new ResizeObserver(() => map.updateSize())
    resize.observe(host.current)
    return () => {
      resize.disconnect()
      map.setTarget(undefined)
      parts.current = null
    }
  }, [])

  // Redraw the shape when the draft changes from anywhere else.
  const { draft, bbox, fitKey, drawing } = props
  useEffect(() => {
    const m = parts.current
    if (!m) return
    if (m.quiet) {
      m.quiet = false
      return
    }
    m.draftSource.clear()
    const ps = draft.positions
    if (ps.length) {
      let geom: Point | LineString | Polygon | null = null
      if (draft.shape === 'Point') geom = new Point(ps[0])
      else if (draft.shape === 'LineString' && ps.length >= 2)
        geom = new LineString(ps)
      else if (draft.shape === 'Polygon' && ps.length >= 3)
        geom = new Polygon([[...ps, ps[0]]])
      else if (ps.length) geom = new Point(ps[0])
      if (geom) m.draftSource.addFeature(new Feature(geom))
      if (
        draft.shape === 'Point' &&
        draft.uncertainty &&
        draft.uncertainty > 0
      ) {
        const ring = circular(ps[0], draft.uncertainty, 48)
        const f = new Feature(ring)
        f.set('uncertainty', true)
        m.draftSource.addFeature(f)
      }
    }
  }, [draft])

  // The allowed area.
  useEffect(() => {
    const m = parts.current
    if (!m) return
    m.areaSource.clear()
    if (!bbox) return
    const [w, s, e, n] = bbox
    const rect = (x0: number, x1: number) =>
      new Feature(
        new Polygon([
          [
            [x0, s],
            [x1, s],
            [x1, n],
            [x0, n],
            [x0, s],
          ],
        ]),
      )
    if (w <= e) m.areaSource.addFeature(rect(w, e))
    else {
      m.areaSource.addFeature(rect(w, 180))
      m.areaSource.addFeature(rect(-180, e))
    }
  }, [bbox])

  // Frame the view.
  useEffect(() => {
    const m = parts.current
    if (!m) return
    const view = m.map.getView()
    const ps = draft.positions
    if (ps.length === 1) {
      view.setCenter(ps[0])
      view.setZoom(Math.max(view.getZoom() ?? 0, 6))
    } else if (ps.length > 1) {
      const xs = ps.map((p) => p[0])
      const ys = ps.map((p) => p[1])
      view.fit(
        [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)],
        {
          padding: [40, 40, 40, 40],
          maxZoom: 14,
        },
      )
    } else if (bbox) {
      const [w, s, e, n] = bbox
      view.fit([w <= e ? w : w - 360, s, e, n], { padding: [30, 30, 30, 30] })
    } else {
      view.setCenter([0, 20])
      view.setZoom(1)
    }
    // Only when asked to: not on every edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey])

  // Drawing a new line or area.
  useEffect(() => {
    const m = parts.current
    if (!m) return
    if (m.draw) {
      m.map.removeInteraction(m.draw)
      m.draw = null
    }
    m.drawSource.clear()
    if (!drawing || draft.shape === 'Point') return
    const draw = new Draw({
      source: m.drawSource,
      type: draft.shape === 'Polygon' ? 'Polygon' : 'LineString',
    })
    draw.on('drawend', (e) => {
      const g = e.feature.getGeometry()
      const coords =
        g instanceof Polygon
          ? g.getCoordinates()[0].slice(0, -1)
          : g instanceof LineString
            ? g.getCoordinates()
            : []
      latest.current.onChange(toPositions(coords))
      latest.current.onDrawEnd()
    })
    m.map.addInteraction(draw)
    m.draw = draw
  }, [drawing, draft.shape])

  return (
    <div
      ref={host}
      role="application"
      aria-label="Map. Click to place or draw; the boxes beside it do the same without a mouse."
      className="h-80 w-full overflow-hidden rounded-md border border-border sm:h-[26rem]"
    />
  )
}
