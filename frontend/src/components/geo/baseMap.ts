import olCss from 'ol/ol.css?inline'
import { addStyles, styleRoot } from '../../utils/host'
import OlMap from 'ol/Map'
import View from 'ol/View'
import VectorLayer from 'ol/layer/Vector'
import VectorSource from 'ol/source/Vector'
import Graticule from 'ol/layer/Graticule'
import TileLayer from 'ol/layer/Tile'
import XYZ from 'ol/source/XYZ'
import GeoJSON from 'ol/format/GeoJSON'
import type BaseLayer from 'ol/layer/Base'
import { Fill, Stroke, Style } from 'ol/style'
import { ScaleLine, Zoom } from 'ol/control'
import { feature as topoFeature } from 'topojson-client'
import type { Topology } from 'topojson-specification'
import landTopology from 'world-atlas/land-50m.json'

/**
 * The base every map in civex is drawn on, with OpenLayers in plain
 * latitude/longitude: bundled coastlines and a graticule, so it works offline
 * and needs no account, under an optional XYZ tile layer (Settings → Map) for
 * street-level detail. The location editor and the explorer's map put their
 * own layers on top (`overlays`).
 */

export interface BaseMapOptions {
  /** Layers drawn above the base, bottom first. */
  overlays: BaseLayer[]
  tileUrl?: string | null
  tileAttribution?: string | null
}

/** A theme colour (a CSS custom property), read when the map is built. */
export const themeColor = (name: string, fallback: string) =>
  getComputedStyle(styleRoot()).getPropertyValue(name).trim() || fallback

/** `color` (a hex or rgb() from the theme) at `alpha` 0..1. */
export function withAlpha(color: string, alpha: number): string {
  const hex = /^#([0-9a-f]{6})$/i.exec(color)
  if (hex) {
    const n = parseInt(hex[1], 16)
    return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
  }
  const rgb = /^rgba?\((\d+)[ ,]+(\d+)[ ,]+(\d+)/.exec(color)
  return rgb ? `rgba(${rgb[1]}, ${rgb[2]}, ${rgb[3]}, ${alpha})` : color
}

/** The credit is plain text; OpenLayers renders attributions as HTML. */
const escapeHtml = (s: string) =>
  s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)

/** Build the map in `target`: the base, then `overlays`, a world view, zoom
 * buttons and a scale. Call `map.setTarget(undefined)` to take it down. */
export function createBaseMap(
  target: HTMLElement,
  { overlays, tileUrl, tileAttribution }: BaseMapOptions,
): OlMap {
  const border = themeColor('--color-border', '#d0d7de')
  const sea = themeColor('--color-canvas-subtle', '#f6f8fa')
  const land = themeColor('--color-canvas-inset', '#eaeef2')

  const landSource = new VectorSource({
    features: new GeoJSON().readFeatures(
      topoFeature(
        landTopology as unknown as Topology,
        (landTopology as unknown as Topology).objects.land,
      ),
    ),
  })
  const base: BaseLayer[] = [
    new VectorLayer({
      source: landSource,
      style: new Style({
        fill: new Fill({ color: land }),
        stroke: new Stroke({ color: border, width: 0.8 }),
      }),
    }),
    new Graticule({
      strokeStyle: new Stroke({ color: border, width: 0.6, lineDash: [2, 4] }),
      showLabels: true,
      wrapX: true,
    }),
  ]
  if (tileUrl)
    base.unshift(
      new TileLayer({
        source: new XYZ({
          url: tileUrl,
          attributions: tileAttribution
            ? escapeHtml(tileAttribution)
            : undefined,
          projection: 'EPSG:3857',
        }),
      }),
    )

  addStyles('ol', olCss)
  const map = new OlMap({
    target,
    layers: [...base, ...overlays],
    controls: [new Zoom(), new ScaleLine({ units: 'metric' })],
    view: new View({
      projection: 'EPSG:4326',
      center: [0, 20],
      zoom: 1,
      minZoom: 0,
      maxZoom: 18,
      multiWorld: true,
    }),
  })
  target.style.background = sea
  return map
}
