import { useEffect, useRef, useState } from 'react'
import {
  type AiConfig,
  type OllamaModel,
  type OpenRouterLimits,
  PRESET_PROVIDERS,
  type PresetProviderId,
  aiApi,
} from '../../api/ai'

function detectPreset(cfg: AiConfig | null): PresetProviderId {
  if (!cfg?.configured) return 'groq'
  if (cfg.provider === 'anthropic') return 'anthropic'
  const groq = PRESET_PROVIDERS.find((p) => p.id === 'groq')!
  const gemini = PRESET_PROVIDERS.find((p) => p.id === 'gemini')!
  const ollama = PRESET_PROVIDERS.find((p) => p.id === 'ollama')!
  const openrouter = PRESET_PROVIDERS.find((p) => p.id === 'openrouter')!
  if (cfg.base_url === groq.base_url) return 'groq'
  if (cfg.base_url === gemini.base_url) return 'gemini'
  if (cfg.base_url === openrouter.base_url) return 'openrouter'
  if (
    cfg.base_url?.startsWith('http://localhost:11434') ||
    cfg.base_url === ollama.base_url
  )
    return 'ollama'
  return 'custom'
}

export default function SettingsPane({ onSaved }: { onSaved: () => void }) {
  const [cfg, setCfg] = useState<AiConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [preset, setPreset] = useState<PresetProviderId>('groq')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [customBaseUrl, setCustomBaseUrl] = useState('')
  const [customModel, setCustomModel] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const [orLimits, setOrLimits] = useState<OpenRouterLimits | null>(null)
  const [orPolling, setOrPolling] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([])
  const [ollamaLoading, setOllamaLoading] = useState(false)
  const [ollamaError, setOllamaError] = useState<string | null>(null)

  useEffect(() => {
    aiApi
      .getConfig()
      .then((c) => {
        setCfg(c)
        const p = detectPreset(c)
        setPreset(p)
        setModel(c.model)
        if (p === 'custom' || p === 'ollama' || p === 'openrouter') {
          setCustomModel(c.model)
        }
        if (p === 'custom' || p === 'ollama') {
          setCustomBaseUrl(c.base_url ?? '')
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const presetObj = PRESET_PROVIDERS.find((p) => p.id === preset)!

  function handlePresetChange(newPreset: PresetProviderId) {
    setPreset(newPreset)
    setError(null)
    const p = PRESET_PROVIDERS.find((x) => x.id === newPreset)!
    if (newPreset === 'openrouter') {
      // Pre-fill with the first free model as a convenient starting point,
      // but the field stays free-text so any paid OpenRouter slug works too.
      setCustomModel(p.models[0]?.id ?? '')
    } else if (newPreset === 'ollama') {
      const ollamaPreset = p as typeof p & { defaultModel?: string }
      setCustomModel(ollamaPreset.defaultModel ?? 'qwen2.5:7b')
      setCustomBaseUrl(p.base_url as string)
    } else if (p.models.length > 0) {
      setModel(p.models[0]?.id ?? '')
    } else {
      setModel(customModel)
    }
  }

  // Reset ollama-specific state as soon as the preset changes away from
  // 'ollama' -- adjusted during render (same pattern as JobsTable's
  // page-reset) rather than a synchronous setState at the top of the effect
  // below, which only needs to own the actual fetch (a real external-system
  // sync) now.
  const [prevPreset, setPrevPreset] = useState(preset)
  if (prevPreset !== preset) {
    setPrevPreset(preset)
    if (preset !== 'ollama') {
      setOllamaModels([])
      setOllamaError(null)
    }
  }

  // Fetch Ollama models whenever the ollama preset is selected or base URL
  // changes. The loading/error reset is inside the first .then() (a
  // microtask away, imperceptibly later than firing synchronously) rather
  // than at the top of the effect body -- keeps the whole fetch sequence in
  // callback form, matching the pattern already used elsewhere in this file
  // (react-hooks/set-state-in-effect flags synchronous setState in an
  // effect's own body, not inside a promise callback).
  useEffect(() => {
    if (preset !== 'ollama') return
    const url = customBaseUrl || 'http://localhost:11434/v1'
    Promise.resolve()
      .then(() => {
        setOllamaLoading(true)
        setOllamaError(null)
        return aiApi.getOllamaModels(url)
      })
      .then((models) => {
        setOllamaModels(models)
        if (models.length > 0) {
          setCustomModel((prev) => prev || models[0].name)
        }
      })
      .catch((e) => setOllamaError(e instanceof Error ? e.message : String(e)))
      .finally(() => setOllamaLoading(false))
  }, [preset, customBaseUrl])

  // Fetch OpenRouter limits whenever we're on the openrouter preset and configured
  useEffect(() => {
    if (!cfg?.configured || detectPreset(cfg) !== 'openrouter') return
    aiApi
      .getOpenRouterLimits()
      .then(setOrLimits)
      .catch(() => {})
    const id = setInterval(
      () =>
        aiApi
          .getOpenRouterLimits()
          .then(setOrLimits)
          .catch(() => {}),
      30_000,
    )
    return () => clearInterval(id)
  }, [cfg])

  // Clean up polling interval on unmount
  useEffect(
    () => () => {
      if (pollRef.current) clearInterval(pollRef.current)
    },
    [],
  )

  async function handleOpenRouterLogin() {
    try {
      const url = await aiApi.getOpenRouterAuthUrl()
      window.open(url, '_blank', 'width=600,height=700')
      setOrPolling(true)
      pollRef.current = setInterval(async () => {
        try {
          const updated = await aiApi.getConfig()
          if (
            updated.configured &&
            updated.base_url?.includes('openrouter.ai')
          ) {
            setCfg(updated)
            setPreset('openrouter')
            setModel(updated.model)
            setOrPolling(false)
            if (pollRef.current) clearInterval(pollRef.current)
            setSuccess(true)
            setTimeout(() => setSuccess(false), 2000)
          }
        } catch {
          /* ignore */
        }
      }, 1500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleSave() {
    setError(null)
    setSuccess(false)
    setSaving(true)
    try {
      const isCustom = preset === 'custom'
      const isOllama = preset === 'ollama'
      const isOpenRouter = preset === 'openrouter'
      const isAnthropic = preset === 'anthropic'
      const provider = isAnthropic ? 'anthropic' : 'openai-compat'
      const base_url = isAnthropic
        ? null
        : isCustom || isOllama
          ? customBaseUrl.trim()
          : (presetObj.base_url as string)
      const resolvedModel =
        isCustom || isOllama || isOpenRouter ? customModel.trim() : model

      const patch: Record<string, unknown> = {
        provider,
        base_url,
        model: resolvedModel,
      }
      if (apiKey.trim()) {
        patch.api_key = apiKey.trim()
      } else if (isOllama) {
        patch.api_key = 'ollama'
      } else if (isOpenRouter && cfg?.configured) {
        // keep existing key from OAuth
      } else if (isOpenRouter && !cfg?.configured) {
        setError(
          'Use the "Login with OpenRouter" button to connect, or paste a key manually.',
        )
        setSaving(false)
        return
      } else if (!cfg?.configured) {
        setError('API key is required')
        setSaving(false)
        return
      }

      const updated = await aiApi.updateConfig(patch)
      setCfg(updated)
      setApiKey('')
      setSuccess(true)
      setTimeout(() => {
        setSuccess(false)
        onSaved()
      }, 1200)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="p-4 text-sm text-[#656d76]">Loading…</div>

  const isCustom = preset === 'custom'
  const isOllama = preset === 'ollama'
  const isOpenRouter = preset === 'openrouter'
  const isFreeText = isCustom || isOllama || isOpenRouter
  const isAnthropic = preset === 'anthropic'
  const effectiveModel = isFreeText ? customModel : model

  return (
    <div className="p-4 space-y-4 text-sm">
      <div>
        <p className="font-semibold text-[#1f2328] mb-1">
          AI Assistant Settings
        </p>
        {cfg?.configured ? (
          <p className="text-xs text-[#3fb950]">
            ✓{' '}
            {cfg.provider === 'anthropic'
              ? 'Claude'
              : cfg.base_url?.includes('groq')
                ? 'Groq'
                : cfg.base_url?.includes('google')
                  ? 'Gemini'
                  : cfg.base_url?.includes('openrouter')
                    ? 'OpenRouter'
                    : cfg.base_url?.includes('11434')
                      ? 'Ollama'
                      : 'Custom'}{' '}
            —{' '}
            {cfg.base_url?.includes('11434') ||
            cfg.base_url?.includes('openrouter')
              ? cfg.model
              : `key ${cfg.key_hint}`}
            {cfg.source === 'env' && (
              <span className="text-[#adbac7] ml-1">(via env)</span>
            )}
          </p>
        ) : (
          <p className="text-xs text-[#f85149]">Not configured</p>
        )}
      </div>

      {/* Provider */}
      <div>
        <label className="block text-xs font-medium text-[#1f2328] mb-1">
          Provider
        </label>
        <select
          value={preset}
          onChange={(e) =>
            handlePresetChange(e.target.value as PresetProviderId)
          }
          className="w-full rounded-md border border-[#d0d7de] px-3 py-2 text-sm text-[#1f2328] bg-white focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
        >
          {PRESET_PROVIDERS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
        {presetObj.docs && !isOllama && (
          <p className="mt-1 text-xs text-[#adbac7]">
            Get a free API key at{' '}
            <a
              href={presetObj.docs}
              target="_blank"
              rel="noreferrer"
              className="text-[#0969da] hover:underline"
            >
              {presetObj.docs.replace('https://', '')}
            </a>
          </p>
        )}
        {isOllama && (
          <p className="mt-1 text-xs text-[#adbac7]">
            {'note' in presetObj ? (presetObj as { note: string }).note : ''}{' '}
            <a
              href="https://ollama.com"
              target="_blank"
              rel="noreferrer"
              className="text-[#0969da] hover:underline"
            >
              ollama.com
            </a>
          </p>
        )}
        {isOpenRouter && (
          <p className="mt-1 text-xs text-[#adbac7]">
            {'note' in presetObj ? (presetObj as { note: string }).note : ''}
          </p>
        )}
      </div>

      {/* Base URL — editable for ollama and custom */}
      {(isCustom || isOllama) && (
        <div>
          <label className="block text-xs font-medium text-[#1f2328] mb-1">
            Base URL
          </label>
          <input
            value={customBaseUrl}
            onChange={(e) => setCustomBaseUrl(e.target.value)}
            placeholder="http://localhost:11434/v1"
            className="w-full rounded-md border border-[#d0d7de] px-3 py-2 text-sm text-[#1f2328] placeholder:text-[#adbac7] focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
          />
          {isOllama && (
            <p className="mt-1 text-xs text-[#adbac7]">
              Change if Ollama runs on a different host/port.
            </p>
          )}
        </div>
      )}

      {/* OpenRouter OAuth + limits */}
      {isOpenRouter && (
        <div className="space-y-2">
          <button
            onClick={handleOpenRouterLogin}
            disabled={orPolling}
            className="w-full py-2 rounded-md border border-[#d0d7de] bg-white text-sm font-medium text-[#1f2328] hover:bg-[#f6f8fa] disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
          >
            {orPolling ? (
              <>
                <svg
                  className="animate-spin w-3.5 h-3.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                >
                  <path
                    d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"
                    strokeLinecap="round"
                  />
                </svg>
                Waiting for login…
              </>
            ) : (
              <>
                {cfg?.configured && detectPreset(cfg) === 'openrouter'
                  ? '↺ Reconnect with OpenRouter'
                  : '→ Login with OpenRouter'}
              </>
            )}
          </button>

          {/* Live limits widget */}
          {orLimits && (
            <div className="rounded-md border border-[#d0d7de] bg-[#f6f8fa] px-3 py-2 text-xs space-y-1">
              <div className="flex justify-between text-[#1f2328]">
                <span className="font-medium">Daily request limit</span>
                <span>
                  {orLimits.data.rate_limit?.requests ?? '—'} /{' '}
                  {orLimits.data.rate_limit?.interval ?? 'day'}
                </span>
              </div>
              {orLimits.data.limit !== null && (
                <div className="flex justify-between text-[#656d76]">
                  <span>Credit usage</span>
                  <span>${orLimits.data.usage.toFixed(4)}</span>
                </div>
              )}
              <div className="flex justify-between text-[#656d76]">
                <span>Free tier</span>
                <span>{orLimits.data.is_free_tier ? 'Yes' : 'No'}</span>
              </div>
              <p className="text-xs text-[#adbac7] pt-1">
                Refreshes every 30 s. Limit resets daily.
              </p>
            </div>
          )}

          <p className="text-xs text-[#adbac7]">
            Or paste a key manually below.
          </p>
        </div>
      )}

      {/* API key */}
      {!isOllama && (
        <div>
          <label className="block text-xs font-medium text-[#1f2328] mb-1">
            API key
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={
              cfg?.configured
                ? `Current: ${cfg.key_hint}`
                : presetObj.key_placeholder
            }
            className="w-full rounded-md border border-[#d0d7de] px-3 py-2 text-sm text-[#1f2328] placeholder:text-[#adbac7] focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
          />
          <p className="mt-1 text-xs text-[#adbac7]">
            {cfg?.configured
              ? 'Leave blank to keep existing key.'
              : 'Required.'}{' '}
            Saved to _civex/config.toml.
          </p>
        </div>
      )}

      {/* Model */}
      <div>
        <label className="block text-xs font-medium text-[#1f2328] mb-1">
          Model
        </label>
        {isOllama ? (
          ollamaLoading ? (
            <div className="flex items-center gap-2 text-xs text-[#656d76] py-2">
              <svg
                className="animate-spin w-3.5 h-3.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
              >
                <path
                  d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"
                  strokeLinecap="round"
                />
              </svg>
              Detecting installed models…
            </div>
          ) : ollamaError ? (
            <div className="space-y-2">
              <p className="text-xs text-[#d1242f]">{ollamaError}</p>
              <p className="text-xs text-[#adbac7]">
                Make sure Ollama is running:{' '}
                <code className="bg-[#eaeef2] px-1 rounded-md">
                  ollama serve
                </code>
              </p>
              <input
                value={customModel}
                onChange={(e) => setCustomModel(e.target.value)}
                placeholder="qwen2.5:7b"
                className="w-full rounded-md border border-[#d0d7de] px-3 py-2 text-sm text-[#1f2328] placeholder:text-[#adbac7] focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
              />
            </div>
          ) : ollamaModels.length === 0 ? (
            <div className="space-y-2">
              <p className="text-xs text-[#656d76]">No models installed.</p>
              <p className="text-xs text-[#adbac7]">
                Run{' '}
                <code className="bg-[#eaeef2] px-1 rounded-md">
                  ollama pull qwen2.5:7b
                </code>{' '}
                then refresh.
              </p>
            </div>
          ) : (
            <div className="space-y-1">
              <select
                value={customModel}
                onChange={(e) => setCustomModel(e.target.value)}
                className="w-full rounded-md border border-[#d0d7de] px-3 py-2 text-sm text-[#1f2328] bg-white focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
              >
                {ollamaModels.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name} —{' '}
                    {m.size >= 1e9
                      ? `${(m.size / 1e9).toFixed(1)} GB`
                      : `${Math.round(m.size / 1e6)} MB`}
                  </option>
                ))}
              </select>
              <p className="text-xs text-[#adbac7]">
                {ollamaModels.length} model
                {ollamaModels.length !== 1 ? 's' : ''} installed. Tool calling
                requires qwen2.5, llama3.1, or mistral.
              </p>
            </div>
          )
        ) : isFreeText || presetObj.models.length === 0 ? (
          <>
            <input
              value={customModel}
              onChange={(e) => setCustomModel(e.target.value)}
              placeholder={
                isAnthropic
                  ? 'claude-sonnet-4-6'
                  : isOpenRouter
                    ? 'e.g. anthropic/claude-3.5-sonnet (paid) or the free options below'
                    : 'model name'
              }
              list={isOpenRouter ? 'openrouter-model-suggestions' : undefined}
              className="w-full rounded-md border border-[#d0d7de] px-3 py-2 text-sm text-[#1f2328] placeholder:text-[#adbac7] focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
            />
            {isOpenRouter && (
              <datalist id="openrouter-model-suggestions">
                {presetObj.models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </datalist>
            )}
          </>
        ) : (
          <select
            value={effectiveModel || presetObj.models[0]?.id || ''}
            onChange={(e) => setModel(e.target.value)}
            className="w-full rounded-md border border-[#d0d7de] px-3 py-2 text-sm text-[#1f2328] bg-white focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
          >
            {presetObj.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        )}
      </div>

      {error && <p className="text-xs text-[#d1242f]">{error}</p>}
      {success && <p className="text-xs text-[#3fb950]">✓ Saved</p>}

      <button
        onClick={handleSave}
        disabled={saving}
        className="w-full py-2 rounded-md bg-[#0969da] text-white text-sm font-medium hover:bg-[#0860ca] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {saving ? 'Saving…' : 'Save'}
      </button>
    </div>
  )
}
