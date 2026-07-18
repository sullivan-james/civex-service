export interface AiConfig {
  configured: boolean
  source: 'config' | 'env' | 'none'
  model: string
  provider: 'anthropic' | 'openai-compat'
  base_url: string | null
  key_hint: string | null
}

export const ANTHROPIC_MODELS = [
  { id: 'claude-haiku-4-5-20251001', label: 'Haiku (fast, cheap)' },
  { id: 'claude-sonnet-4-6', label: 'Sonnet (balanced)' },
  { id: 'claude-opus-4-8', label: 'Opus (most capable)' },
]

export const PRESET_PROVIDERS = [
  {
    id: 'anthropic',
    label: 'Anthropic (Claude)',
    base_url: null,
    key_placeholder: 'sk-ant-...',
    models: ANTHROPIC_MODELS.map((m) => ({ id: m.id, label: m.label })),
    docs: null,
  },
  {
    id: 'groq',
    label: 'Groq — free tier',
    base_url: 'https://api.groq.com/openai/v1',
    key_placeholder: 'gsk_...',
    models: [
      { id: 'llama-3.3-70b-versatile', label: 'Llama 3.3 70B (recommended)' },
      { id: 'llama-3.1-8b-instant', label: 'Llama 3.1 8B (fastest)' },
      { id: 'mixtral-8x7b-32768', label: 'Mixtral 8x7B' },
    ],
    docs: 'https://console.groq.com/keys',
  },
  {
    id: 'gemini',
    label: 'Google Gemini — free tier',
    base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/',
    key_placeholder: 'AIza...',
    models: [
      { id: 'gemini-1.5-flash', label: 'Gemini 1.5 Flash (recommended)' },
      { id: 'gemini-1.5-pro', label: 'Gemini 1.5 Pro' },
      { id: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
    ],
    docs: 'https://aistudio.google.com/app/apikey',
  },
  {
    id: 'openrouter',
    label: 'OpenRouter — free models',
    base_url: 'https://openrouter.ai/api/v1',
    key_placeholder: 'sk-or-...',
    models: [
      {
        id: 'meta-llama/llama-3.1-8b-instruct:free',
        label: 'Llama 3.1 8B (free)',
      },
      { id: 'qwen/qwen3-8b:free', label: 'Qwen3 8B (free)' },
      { id: 'google/gemma-3-12b-it:free', label: 'Gemma 3 12B (free)' },
      { id: 'mistralai/mistral-7b-instruct:free', label: 'Mistral 7B (free)' },
    ],
    docs: null,
    note: '50 free requests/day. No card required.',
  },
  {
    id: 'ollama',
    label: 'Ollama — local',
    base_url: 'http://localhost:11434/v1',
    key_placeholder: 'ollama',
    models: [],
    docs: 'https://ollama.com',
    defaultModel: 'qwen2.5:7b',
    note: 'Run locally — no API key needed. Models must support tool calling: qwen2.5, llama3.1, mistral.',
  },
  {
    id: 'custom',
    label: 'Custom (OpenAI-compatible)',
    base_url: '',
    key_placeholder: 'API key',
    models: [],
    docs: null,
  },
] as const

export type PresetProviderId = (typeof PRESET_PROVIDERS)[number]['id']

export async function getAiConfig(): Promise<AiConfig> {
  const res = await fetch('/api/ai/config')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function updateAiConfig(patch: {
  api_key?: string
  model?: string
  provider?: string
  base_url?: string | null
}): Promise<AiConfig> {
  const res = await fetch('/api/ai/config', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as Record<string, unknown>
    throw new Error((err.detail as string) ?? `HTTP ${res.status}`)
  }
  return res.json()
}

export interface OllamaModel {
  name: string
  size: number // bytes
}

export async function getOllamaModels(
  baseUrl: string = 'http://localhost:11434/v1',
): Promise<OllamaModel[]> {
  const res = await fetch(
    `/api/ai/ollama/models?base_url=${encodeURIComponent(baseUrl)}`,
  )
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as Record<string, unknown>
    throw new Error((err.detail as string) ?? `HTTP ${res.status}`)
  }
  const { models } = (await res.json()) as { models: OllamaModel[] }
  return models
}

export interface OpenRouterLimits {
  data: {
    label: string
    usage: number
    limit: number | null
    is_free_tier: boolean
    rate_limit: { requests: number; interval: string } | null
  }
}

export async function getOpenRouterAuthUrl(): Promise<string> {
  const res = await fetch('/api/ai/openrouter/auth-url')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const { url } = (await res.json()) as { url: string }
  return url
}

export async function getOpenRouterLimits(): Promise<OpenRouterLimits> {
  const res = await fetch('/api/ai/openrouter/limits')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// Mirrors civex.server.routers.ai's UserMessage/AssistantMessage/ToolCallMessage
// discriminated union. tool_call entries carry a prior tool call + its result
// verbatim, so resending them lets the model see tool calls it made (and what
// they returned) in an earlier turn, even though each /api/ai/chat request is
// otherwise stateless.
export type ChatMessage =
  | { role: 'user'; content: string }
  | { role: 'assistant'; content: string }
  | {
      role: 'tool_call'
      id: string
      name: string
      input: Record<string, unknown>
      result: string
    }

export type AiEvent =
  | { type: 'text_delta'; delta: string }
  | {
      type: 'tool_use_start'
      id: string
      name: string
      input: Record<string, unknown>
    }
  | { type: 'tool_result'; tool_use_id: string; content: string }
  | { type: 'done' }
  | { type: 'error'; message: string }

export async function* streamChat(
  messages: ChatMessage[],
): AsyncGenerator<AiEvent> {
  const res = await fetch('/api/ai/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
  })
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as Record<string, unknown>
    throw new Error((err.detail as string) ?? `HTTP ${res.status}`)
  }
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          yield JSON.parse(line.slice(6)) as AiEvent
        } catch {
          // skip malformed lines
        }
      }
    }
  }
}
