import { api } from './client'
import { parseSSE } from '../lib/sse'

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

// Only Ollama + OpenRouter are offered as selectable providers -- fewer
// options, less confusion. Anthropic/Groq/Gemini are disabled (not deleted)
// below so re-enabling one later is a matter of moving it back into the
// array, not re-deriving it from scratch.
export const PRESET_PROVIDERS = [
  /*
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
  */
  {
    id: 'openrouter',
    label: 'OpenRouter',
    base_url: 'https://openrouter.ai/api/v1',
    key_placeholder: 'sk-or-...',
    // Quick-pick suggestions only -- the model field is free-text, so any
    // OpenRouter slug works even if it's not in this list. Kept broad
    // across providers/price points; verify against
    // https://openrouter.ai/api/v1/models if entries here start 404ing
    // (OpenRouter deprecates/renames slugs over time).
    models: [
      // Free tier
      { id: 'tencent/hy3:free', label: 'Tencent Hy3 (free)' },
      { id: 'poolside/laguna-m.1:free', label: 'Poolside Laguna M.1 (free)' },
      {
        id: 'poolside/laguna-xs-2.1:free',
        label: 'Poolside Laguna XS 2.1 (free)',
      },
      {
        id: 'cohere/north-mini-code:free',
        label: 'Cohere North Mini Code (free)',
      },
      {
        id: 'nvidia/nemotron-3-ultra-550b-a55b:free',
        label: 'NVIDIA Nemotron 3 Ultra 550B (free)',
      },
      // Paid — Anthropic
      { id: 'anthropic/claude-sonnet-5', label: 'Claude Sonnet 5' },
      { id: 'anthropic/claude-opus-4.8', label: 'Claude Opus 4.8' },
      { id: 'anthropic/claude-fable-5', label: 'Claude Fable 5' },
      // Paid — OpenAI
      { id: 'openai/gpt-5.6-sol', label: 'GPT-5.6 Sol (frontier reasoning)' },
      { id: 'openai/gpt-5.6-terra', label: 'GPT-5.6 Terra (balanced)' },
      { id: 'openai/gpt-5.6-luna', label: 'GPT-5.6 Luna (fast, cheap)' },
      // Paid — Google
      { id: 'google/gemini-3.5-flash', label: 'Gemini 3.5 Flash' },
      { id: 'google/gemini-3.1-flash-lite', label: 'Gemini 3.1 Flash Lite' },
      // Paid — Meta / Mistral / xAI / Qwen / others
      { id: 'meta/muse-spark-1.1', label: 'Meta Muse Spark 1.1' },
      { id: 'mistralai/mistral-medium-3.5', label: 'Mistral Medium 3.5' },
      { id: 'x-ai/grok-4.5', label: 'Grok 4.5' },
      { id: 'qwen/qwen3.7-max', label: 'Qwen3.7 Max' },
      { id: 'qwen/qwen3.7-plus', label: 'Qwen3.7 Plus' },
      { id: 'z-ai/glm-5.2', label: 'GLM-5.2' },
    ],
    docs: null,
    note: 'Type any OpenRouter model slug — the free ones above are rate-limited (50 req/day); anything else uses your OpenRouter credits.',
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

export interface OllamaModel {
  name: string
  size: number // bytes
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

export interface UsageTotals {
  requests: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
}

export interface ModelUsage extends UsageTotals {
  provider: string
  model: string
}

export interface AiUsageResponse {
  total: UsageTotals
  by_model: ModelUsage[]
}

export const aiApi = {
  getConfig: () => api.get<AiConfig>('/ai/config'),
  updateConfig: (patch: {
    api_key?: string
    model?: string
    provider?: string
    base_url?: string | null
  }) => api.patch<AiConfig>('/ai/config', patch),
  getOllamaModels: async (
    baseUrl: string = 'http://localhost:11434/v1',
  ): Promise<OllamaModel[]> => {
    const { models } = await api.get<{ models: OllamaModel[] }>(
      `/ai/ollama/models?base_url=${encodeURIComponent(baseUrl)}`,
    )
    return models
  },
  getOpenRouterAuthUrl: async (): Promise<string> => {
    const { url } = await api.get<{ url: string }>('/ai/openrouter/auth-url')
    return url
  },
  getOpenRouterLimits: () => api.get<OpenRouterLimits>('/ai/openrouter/limits'),
  getUsage: () => api.get<AiUsageResponse>('/ai/usage'),
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
  | { type: 'usage'; input_tokens: number; output_tokens: number }
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
  for await (const data of parseSSE(res.body!.getReader())) {
    try {
      yield JSON.parse(data) as AiEvent
    } catch {
      // skip malformed lines
    }
  }
}
