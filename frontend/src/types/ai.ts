/** Shared chat-entry domain types for the AI panel -- consumed by
 * hooks/useAiChat.ts and every components/ai/*.tsx piece (CIVEX-57/58). */

export type UserEntry = { kind: 'user'; text: string }
export type AssistantEntry = {
  kind: 'assistant'
  text: string
  streaming: boolean
  // Set when this entry is reporting a failure (stream error, timeout,
  // cancellation) rather than model output, so it can be styled distinctly
  // instead of relying on a symbol embedded in the text itself.
  error?: boolean
}
export type ToolCallEntry = {
  kind: 'tool_call'
  id: string
  name: string
  input: Record<string, unknown>
  result: string | null
  // Set once the user resolves a proposed change. Persisted so the approval
  // prompt does not reappear after a reload.
  outcome?: 'approved' | 'cancelled' | 'error'
  outcomeLabel?: string
}
export type ChatEntry = UserEntry | AssistantEntry | ToolCallEntry

export interface ApprovalResolution {
  outcome: 'approved' | 'cancelled' | 'error'
  outcomeLabel?: string
}
export type ResolvedEntry = { id: string } & ApprovalResolution

export interface StoredSession {
  id: string
  title: string
  createdAt: string
  entries: ChatEntry[]
}
