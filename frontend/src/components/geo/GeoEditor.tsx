import { lazy, Suspense, useMemo, useRef, useState } from 'react'
import { Button, Input, Select, Skeleton } from '../ui'
import { locationProblem, toWkt, type Geometry } from '../../utils/geo'
import {
  COORD_FORMATS,
  formatCoordinate,
  type CoordFormat,
} from '../../utils/geoCoords'
import {
  SHAPE_LABEL,
  draftFromGeometry,
  editableShapes,
  emptyDraft,
  geometryFromDraft,
  type Draft,
  type Position,
  type Shape,
} from '../../utils/geoDraft'
import {
  formatArea,
  formatLength,
  lineLengthMeters,
  ringAreaSqMeters,
} from '../../utils/geoMeasure'
import {
  IMPORT_ACCEPT,
  readFileText,
  readLocations,
  type Candidate,
} from '../../utils/geoImport'
import { CoordinateFields } from './CoordinateFields'
import { VertexTable } from './VertexTable'

// The map (OpenLayers and the coastlines) is a separate chunk, fetched only
// when someone opens the editor.
const GeoMap = lazy(() => import('./GeoMap'))

export interface MapSettings {
  tileUrl: string | null
  attribution: string | null
}

type Rules = { geometry_types?: unknown; bbox?: unknown }

/** Place, draw or import a location. Works on a draft: nothing is saved to
 * the field until the caller applies it. */
export function GeoEditor({
  value,
  rules,
  onApply,
  onCancel,
  map,
}: {
  value: Geometry | null
  rules: Rules
  onApply: (g: Geometry | null) => void
  onCancel: () => void
  map?: MapSettings
}) {
  const shapes = editableShapes(rules)
  const box =
    Array.isArray(rules.bbox) && rules.bbox.length === 4
      ? (rules.bbox as number[])
      : null
  const initial = useMemo(
    () => draftFromGeometry(value, shapes[0] ?? 'Point'),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )
  const [draft, setDraft] = useState<Draft>(initial.draft)
  const [unsupported, setUnsupported] = useState(initial.unsupported)
  const [format, setFormat] = useState<CoordFormat>('dd')
  const [hover, setHover] = useState<[number, number] | null>(null)
  const [fitKey, setFitKey] = useState(0)
  const [drawing, setDrawing] = useState(
    initial.draft.shape !== 'Point' &&
      initial.draft.positions.length === 0 &&
      !initial.unsupported,
  )
  const [locating, setLocating] = useState<string | null>(null)
  const [candidates, setCandidates] = useState<Candidate[] | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const { geometry, problem: shapeProblem } = geometryFromDraft(draft)
  const ruleProblem = geometry ? locationProblem(geometry, rules) : null
  const problem = shapeProblem ?? ruleProblem
  const changed = JSON.stringify(geometry) !== JSON.stringify(value)
  const point = draft.shape === 'Point' ? draft.positions[0] : undefined

  function load(g: Geometry) {
    const { draft: d, unsupported: u } = draftFromGeometry(g, draft.shape)
    setDraft(d)
    setUnsupported(u)
    setDrawing(false)
    setFitKey((k) => k + 1)
  }

  function chooseShape(shape: Shape) {
    if (shape === draft.shape) return
    setDraft(emptyDraft(shape))
    setUnsupported(null)
    setDrawing(shape !== 'Point')
  }

  function setPositions(positions: Position[]) {
    setUnsupported(null)
    setDraft((d) => ({ ...d, positions }))
  }

  function locate() {
    if (!navigator.geolocation)
      return setLocating('This browser can’t share a location.')
    setLocating('Finding your position…')
    navigator.geolocation.getCurrentPosition(
      (p) => {
        const alt = p.coords.altitude
        setDraft({
          shape: 'Point',
          positions: [[p.coords.longitude, p.coords.latitude]],
          elevation:
            alt === null || Number.isNaN(alt)
              ? null
              : Math.round(alt * 10) / 10,
          uncertainty: Math.round(p.coords.accuracy),
        })
        setUnsupported(null)
        setFitKey((k) => k + 1)
        setLocating(
          `Position found, accurate to about ${Math.round(p.coords.accuracy)} m.`,
        )
      },
      (e) =>
        setLocating(
          e.code === e.PERMISSION_DENIED
            ? 'Location sharing was declined.'
            : 'Couldn’t get a position.',
        ),
      { enableHighAccuracy: true, timeout: 15000 },
    )
  }

  async function onFile(file: File | undefined) {
    if (!file) return
    setImportError(null)
    setCandidates(null)
    try {
      const found = await readLocations(await readFileText(file), file.name)
      if (!found.length) setImportError('No locations found in that file.')
      else if (found.length === 1) applyCandidate(found[0])
      else setCandidates(found)
    } catch {
      setImportError(
        'Couldn’t read that file. GeoJSON, GPX, KML and WKT are supported.',
      )
    }
  }

  function applyCandidate(c: Candidate) {
    const type = c.geometry.type as Shape
    if (!shapes.includes(type)) {
      setImportError(
        `That is a ${SHAPE_LABEL[type as Shape]?.toLowerCase() ?? c.geometry.type}, but this field takes ${shapes.map((s) => SHAPE_LABEL[s].toLowerCase()).join(' or ')}.`,
      )
      return
    }
    setImportError(null)
    setCandidates(null)
    load(c.geometry)
  }

  async function copy(kind: 'GeoJSON' | 'WKT') {
    if (!geometry) return
    const text = kind === 'GeoJSON' ? JSON.stringify(geometry) : toWkt(geometry)
    try {
      await navigator.clipboard.writeText(text)
      setCopied(`${kind} copied.`)
    } catch {
      setCopied('Couldn’t copy. Select and copy it from the text below.')
    }
  }

  const noun = draft.shape === 'Polygon' ? 'corner' : 'point'
  const measure =
    geometry?.type === 'LineString'
      ? formatLength(lineLengthMeters(geometry.coordinates as number[][]))
      : geometry?.type === 'Polygon'
        ? formatArea(
            ringAreaSqMeters((geometry.coordinates as number[][][])[0]),
          )
        : null

  if (shapes.length === 0)
    return (
      <div className="space-y-3">
        <p className="text-sm text-fg-muted">
          This field only takes shapes the map editor can’t draw. Enter GeoJSON
          in the text box on the form instead.
        </p>
        <Button onClick={onCancel}>Close</Button>
      </div>
    )

  return (
    <div className="space-y-4">
      {shapes.length > 1 && (
        <div role="tablist" aria-label="Shape" className="flex gap-1">
          {shapes.map((s) => (
            <button
              key={s}
              role="tab"
              type="button"
              aria-selected={draft.shape === s}
              onClick={() => chooseShape(s)}
              className={`rounded-md border px-3 py-1 text-sm cursor-pointer ${
                draft.shape === s
                  ? 'border-accent bg-accent-subtle font-medium text-accent'
                  : 'border-border bg-canvas hover:bg-canvas-subtle'
              }`}
            >
              {SHAPE_LABEL[s]}
            </button>
          ))}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="space-y-1.5">
          <Suspense
            fallback={<Skeleton className="h-80 w-full sm:h-[26rem]" />}
          >
            <GeoMap
              draft={draft}
              bbox={box}
              fitKey={fitKey}
              drawing={drawing}
              onChange={setPositions}
              onDrawEnd={() => setDrawing(false)}
              onHover={(lon, lat) => setHover([lon, lat])}
              tileUrl={map?.tileUrl}
              tileAttribution={map?.attribution}
            />
          </Suspense>
          <p
            className="min-h-4 font-mono text-xs text-fg-muted"
            aria-live="off"
          >
            {hover
              ? `${formatCoordinate(hover[1], 'lat', format)}, ${formatCoordinate(hover[0], 'lon', format)}`
              : draft.shape === 'Point'
                ? 'Click the map to place the point; drag it to move.'
                : drawing
                  ? 'Click to add each point; double-click to finish.'
                  : 'Drag a point to move it; drag the midpoint of a segment to add one.'}
          </p>
          {box && (
            <p className="text-xs text-fg-subtle">
              The dashed box is the area this field allows.
            </p>
          )}
        </div>

        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <label
              htmlFor="coord-format"
              className="text-xs font-medium text-fg-muted"
            >
              Coordinates as
            </label>
            <Select
              id="coord-format"
              size="sm"
              value={format}
              onChange={(e) => setFormat(e.target.value as CoordFormat)}
              className="w-64"
            >
              {COORD_FORMATS.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </Select>
          </div>

          {unsupported && (
            <p
              role="status"
              className="rounded-md bg-attention-subtle px-3 py-2 text-sm text-fg"
            >
              {unsupported}
            </p>
          )}

          {draft.shape === 'Point' ? (
            <>
              <CoordinateFields
                lat={point ? point[1] : null}
                lon={point ? point[0] : null}
                format={format}
                onChange={(lat, lon) => {
                  if (lat === null && lon === null) setPositions([])
                  else
                    setPositions([
                      [lon ?? point?.[0] ?? 0, lat ?? point?.[1] ?? 0],
                    ])
                }}
              />
              <div className="flex flex-wrap gap-4">
                <label className="flex flex-col gap-0.5 text-xs text-fg-muted">
                  Elevation (m, negative below sea level)
                  <Input
                    size="sm"
                    type="number"
                    step="any"
                    value={draft.elevation ?? ''}
                    placeholder="optional"
                    onChange={(e) =>
                      setDraft((d) => ({
                        ...d,
                        elevation:
                          e.target.value === '' ? null : Number(e.target.value),
                      }))
                    }
                    className="w-40"
                  />
                </label>
                <label className="flex flex-col gap-0.5 text-xs text-fg-muted">
                  Uncertainty ± (m)
                  <Input
                    size="sm"
                    type="number"
                    min="0"
                    step="any"
                    value={draft.uncertainty ?? ''}
                    placeholder="optional"
                    onChange={(e) =>
                      setDraft((d) => ({
                        ...d,
                        uncertainty:
                          e.target.value === '' || Number(e.target.value) < 0
                            ? null
                            : Number(e.target.value),
                      }))
                    }
                    className="w-32"
                  />
                </label>
              </div>
              <div className="space-y-1">
                <Button size="sm" onClick={locate}>
                  Use my current position
                </Button>
                {locating && (
                  <p role="status" className="text-xs text-fg-muted">
                    {locating}
                  </p>
                )}
              </div>
            </>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant={drawing ? 'primary' : 'default'}
                  onClick={() => {
                    if (!drawing) setDraft((d) => ({ ...d, positions: [] }))
                    setDrawing(!drawing)
                  }}
                >
                  {drawing
                    ? 'Stop drawing'
                    : draft.positions.length
                      ? 'Redraw on map'
                      : 'Draw on map'}
                </Button>
                {draft.shape === 'LineString' && draft.positions.length > 1 && (
                  <Button
                    size="sm"
                    onClick={() => setPositions([...draft.positions].reverse())}
                  >
                    Reverse direction
                  </Button>
                )}
                {measure && (
                  <span className="text-sm text-fg-muted">
                    {draft.shape === 'LineString' ? 'Length' : 'Area'}:{' '}
                    <strong className="text-fg">{measure}</strong>
                    {` · ${draft.positions.length.toLocaleString()} ${noun}s`}
                  </span>
                )}
              </div>
              <VertexTable
                positions={draft.positions}
                noun={noun}
                onChange={setPositions}
              />
            </>
          )}

          <details className="rounded-md border border-border px-3 py-2">
            <summary className="cursor-pointer select-none text-sm font-medium text-fg">
              Import from a file
            </summary>
            <div className="mt-2 space-y-2">
              <p className="text-xs text-fg-muted">
                GeoJSON, GPX (a GPS track or waypoint), KML (Google Earth) or
                WKT. It fills the editor; nothing is saved until you apply.
              </p>
              <input
                ref={fileInput}
                type="file"
                accept={IMPORT_ACCEPT}
                aria-label="Import a location file"
                onChange={(e) => {
                  void onFile(e.target.files?.[0])
                  e.target.value = ''
                }}
                className="block text-sm file:mr-3 file:rounded-md file:border-0 file:bg-canvas-subtle file:px-3 file:py-1.5 file:text-xs"
              />
              {candidates && (
                <ul className="space-y-1" aria-label="Locations in the file">
                  {candidates.map((c, i) => (
                    <li key={i}>
                      <button
                        type="button"
                        onClick={() => applyCandidate(c)}
                        className="w-full rounded border border-border px-2 py-1 text-left text-sm hover:bg-canvas-subtle cursor-pointer"
                      >
                        {c.label}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {importError && (
                <p role="alert" className="text-xs text-danger">
                  {importError}
                </p>
              )}
            </div>
          </details>

          {geometry && (
            <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
              <span>Copy as</span>
              <Button size="sm" onClick={() => void copy('GeoJSON')}>
                GeoJSON
              </Button>
              <Button size="sm" onClick={() => void copy('WKT')}>
                WKT
              </Button>
              {copied && <span role="status">{copied}</span>}
            </div>
          )}
        </div>
      </div>

      {problem && (
        <p role="alert" className="text-sm text-danger">
          {problem}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
        <Button
          variant="primary"
          disabled={
            !!problem || !changed || (geometry === null && value === null)
          }
          onClick={() => onApply(geometry)}
        >
          {geometry === null && value !== null ? 'Clear location' : 'Apply'}
        </Button>
        <Button onClick={onCancel}>Cancel</Button>
        {value && geometry && (
          <Button variant="danger" onClick={() => onApply(null)}>
            Remove location
          </Button>
        )}
      </div>
    </div>
  )
}
