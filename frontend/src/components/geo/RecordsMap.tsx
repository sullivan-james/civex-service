import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import type OlMap from 'ol/Map'
import Feature from 'ol/Feature'
import VectorLayer from 'ol/layer/Vector'
import VectorSource from 'ol/source/Vector'
import Cluster from 'ol/source/Cluster'
import GeoJSON from 'ol/format/GeoJSON'
import { Point } from 'ol/geom'
import type Geometry from 'ol/geom/Geometry'
import { createEmpty, extend, getHeight, getWidth, isEmpty } from 'ol/extent'
import {
  Circle as CircleStyle,
  Fill,
  Stroke,
  Style,
  Text as TextStyle,
} from 'ol/style'
import type { RecordPoint } from '../../api/records'
import { IconButton } from '../ui'
import { X } from '../ui/icons'
import { createBaseMap, themeColor, withAlpha } from './baseMap'

/**
 * The records a list shows, on a map: points gathered into clusters where
 * they crowd (a number says how many), lines and areas drawn as they are.
 * Clicking a cluster zooms into it; clicking a record, or a cluster that
 * can't be pulled apart (records at one place), names them, each a link to
 * its page. The view fits the records whenever they change.
 */

export interface RecordsMapProps {
  points: RecordPoint[]
  tileUrl?: string | null
  tileAttribution?: string | null
  /** Tailwind height of the map (default: the full map's). */
  height?: string
}

/** How many names a popup lists before "and N more". */
const POPUP_NAMES = 10
/** Points closer than this many pixels are drawn as one cluster. */
const CLUSTER_DISTANCE = 36

interface Picked {
  x: number
  y: number
  records: { id: string; name: string | null }[]
}

export default function RecordsMap({
  points,
  tileUrl,
  tileAttribution,
  height = 'h-[28rem]',
}: RecordsMapProps) {
  const host = useRef<HTMLDivElement>(null)
  const parts = useRef<{
    map: OlMap
    pointSource: VectorSource
    shapeSource: VectorSource
  } | null>(null)
  const [picked, setPicked] = useState<Picked | null>(null)
  const tiles = useRef({ tileUrl, tileAttribution })

  // Build the map once.
  useEffect(() => {
    if (!host.current) return
    const mark = themeColor('--color-chart-1', '#17569e')
    const ring = themeColor('--color-canvas', '#ffffff')
    const pointSource = new VectorSource()
    const shapeSource = new VectorSource()
    const styles = new Map<number, Style>()
    const clusterStyle = (f: Feature) => {
      const n = (f.get('features') as Feature[] | undefined)?.length ?? 1
      let style = styles.get(n)
      if (!style) {
        style = new Style({
          image: new CircleStyle({
            radius: n === 1 ? 5 : Math.min(8 + Math.log10(n) * 6, 22),
            fill: new Fill({ color: n === 1 ? mark : withAlpha(mark, 0.85) }),
            stroke: new Stroke({ color: ring, width: 2 }),
          }),
          text:
            n === 1
              ? undefined
              : new TextStyle({
                  text: n.toLocaleString(),
                  font: '600 11px system-ui, sans-serif',
                  fill: new Fill({ color: ring }),
                }),
        })
        styles.set(n, style)
      }
      return style
    }
    const map = createBaseMap(host.current, {
      ...tiles.current,
      overlays: [
        new VectorLayer({
          source: shapeSource,
          style: new Style({
            stroke: new Stroke({ color: mark, width: 2 }),
            fill: new Fill({ color: withAlpha(mark, 0.12) }),
          }),
        }),
        new VectorLayer({
          source: new Cluster({
            source: pointSource,
            distance: CLUSTER_DISTANCE,
          }),
          style: clusterStyle as never,
        }),
      ],
    })
    parts.current = { map, pointSource, shapeSource }

    map.on('singleclick', (e) => {
      const hit = map.forEachFeatureAtPixel(e.pixel, (f) => f as Feature, {
        hitTolerance: 4,
      })
      if (!hit) {
        setPicked(null)
        return
      }
      const members = (hit.get('features') as Feature[] | undefined) ?? [hit]
      if (members.length > 1) {
        const extent = createEmpty()
        for (const m of members) {
          const g = m.getGeometry()
          if (g) extend(extent, g.getExtent())
        }
        const view = map.getView()
        // Spread out: zoom in. At one place (or as far in as it goes): name them.
        if (
          (getWidth(extent) > 0 || getHeight(extent) > 0) &&
          (view.getZoom() ?? 0) < (view.getMaxZoom() ?? 18) - 1
        ) {
          setPicked(null)
          view.fit(extent, { padding: [60, 60, 60, 60], duration: 250 })
          return
        }
      }
      setPicked({
        x: e.pixel[0],
        y: e.pixel[1],
        records: members.map((m) => ({
          id: String(m.get('id')),
          name: (m.get('name') as string | null) ?? null,
        })),
      })
    })
    map.on('movestart', () => setPicked(null))
    map.on('pointermove', (e) => {
      const el = map.getTargetElement()
      if (el)
        el.style.cursor = map.hasFeatureAtPixel(e.pixel, { hitTolerance: 4 })
          ? 'pointer'
          : ''
    })

    const resize = new ResizeObserver(() => map.updateSize())
    resize.observe(host.current)
    return () => {
      resize.disconnect()
      map.setTarget(undefined)
      parts.current = null
    }
  }, [])

  // Draw the records and fit the view to them.
  useEffect(() => {
    const m = parts.current
    if (!m) return
    setPicked(null)
    const format = new GeoJSON()
    const dots: Feature[] = []
    const shapes: Feature[] = []
    for (const p of points) {
      let geometry: Geometry
      try {
        geometry = format.readGeometry(p.geometry)
      } catch {
        continue // a value this reader doesn't know: leave it out
      }
      const f = new Feature({ geometry, id: p.id, name: p.name })
      ;(geometry instanceof Point ? dots : shapes).push(f)
    }
    m.pointSource.clear()
    m.shapeSource.clear()
    m.pointSource.addFeatures(dots)
    m.shapeSource.addFeatures(shapes)
    const extent = createEmpty()
    for (const f of [...dots, ...shapes]) {
      const g = f.getGeometry()
      if (g) extend(extent, g.getExtent())
    }
    const view = m.map.getView()
    if (isEmpty(extent)) {
      view.setCenter([0, 20])
      view.setZoom(1)
    } else view.fit(extent, { padding: [40, 40, 40, 40], maxZoom: 12 })
  }, [points])

  return (
    <div className="relative">
      <div
        ref={host}
        role="application"
        aria-label="Map of the records listed. Click a record to see its name; a cluster to zoom in."
        className={`${height} w-full overflow-hidden rounded-md border border-border`}
      />
      {picked && (
        <div
          className="absolute z-10 max-h-64 w-64 overflow-auto rounded-md border border-border bg-canvas p-2 text-sm shadow-md"
          style={{
            left: Math.max(4, picked.x - 128),
            top: picked.y + 12,
          }}
        >
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="text-xs text-fg-muted">
              {picked.records.length === 1
                ? 'Record here'
                : `${picked.records.length.toLocaleString()} records here`}
            </span>
            <IconButton
              icon={X}
              aria-label="Close"
              onClick={() => setPicked(null)}
            />
          </div>
          <ul className="space-y-1">
            {picked.records.slice(0, POPUP_NAMES).map((r) => (
              <li key={r.id}>
                <Link
                  className="text-accent hover:underline"
                  to={`/records/${r.id}`}
                >
                  {r.name ?? r.id.slice(0, 8)}
                </Link>
              </li>
            ))}
          </ul>
          {picked.records.length > POPUP_NAMES && (
            <p className="mt-1 text-xs text-fg-muted">
              and {(picked.records.length - POPUP_NAMES).toLocaleString()} more
            </p>
          )}
        </div>
      )}
    </div>
  )
}
