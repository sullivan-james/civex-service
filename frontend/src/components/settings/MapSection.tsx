import { useState } from 'react'
import { errorMessage } from '../../lib/errors'
import { settingsApi } from '../../api/settings'
import { setMapSettings, useMapSettings } from '../../hooks/useMapSettings'
import { Button, Field, Input, Skeleton } from '../ui'

const SAMPLE = 'https://tile.example.org/{z}/{x}/{y}.png'

function MapForm({ url, credit }: { url: string; credit: string }) {
  const [tileUrl, setTileUrl] = useState(url)
  const [attribution, setAttribution] = useState(credit)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const dirty = tileUrl !== url || attribution !== credit

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const saved = await settingsApi.updateMap({
        tile_url: tileUrl.trim() || null,
        attribution: attribution.trim() || null,
      })
      setMapSettings(saved)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-xl space-y-3">
      <Field
        label="Map tile URL"
        info={`An XYZ tile server with {z}, {x} and {y}, for example ${SAMPLE}. Leave empty to use only the built-in coastlines.`}
      >
        <Input
          value={tileUrl}
          onChange={(e) => setTileUrl(e.target.value)}
          placeholder="Built-in coastlines only"
          className="font-mono"
        />
      </Field>
      {tileUrl.trim() && (
        <Field
          label="Credit shown on the map"
          info="Plain text, as the tile provider asks for it."
        >
          <Input
            value={attribution}
            onChange={(e) => setAttribution(e.target.value)}
            placeholder="© OpenStreetMap contributors"
          />
        </Field>
      )}
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
      <Button size="sm" disabled={!dirty || saving} onClick={() => void save()}>
        {saving ? 'Saving…' : 'Save'}
      </Button>
    </div>
  )
}

export default function MapSection() {
  const settings = useMapSettings()
  return (
    <div>
      {!settings ? (
        <Skeleton className="h-9 w-80" />
      ) : (
        <MapForm
          key={`${settings.tile_url}|${settings.attribution}`}
          url={settings.tile_url ?? ''}
          credit={settings.attribution ?? ''}
        />
      )}
    </div>
  )
}
