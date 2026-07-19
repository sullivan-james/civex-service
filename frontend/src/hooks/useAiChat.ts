import { useState } from 'react'
import { type AiEvent, type ChatMessage, streamChat } from '../api/ai'
import type {
  ChatEntry,
  ResolvedEntry,
  ToolCallEntry,
  UserEntry,
} from '../types/ai'

// What the model sees for a tool_call on later turns must reflect what
// actually happened, not the original "proposed" status forever -- otherwise
// it can never tell whether to build on an approved change, back off after a
// cancellation, or retry after an error. Layers the real outcome on top of
// the original result JSON.
function resultForApi(e: ToolCallEntry): string {
  if (!e.outcome) return e.result ?? ''
  try {
    const parsed = JSON.parse(e.result ?? '{}') as Record<string, unknown>
    if (e.outcome === 'approved') {
      return JSON.stringify({
        ...parsed,
        status: 'approved',
        note: e.outcomeLabel
          ? `Approved and applied: ${e.outcomeLabel}`
          : 'The user approved this change; it has been applied.',
      })
    }
    if (e.outcome === 'cancelled') {
      return JSON.stringify({
        ...parsed,
        status: 'cancelled',
        note: 'The user did not approve this change. Do not retry it unless asked again.',
      })
    }
    return JSON.stringify({
      ...parsed,
      status: 'error',
      message: e.outcomeLabel ?? 'Applying this change failed.',
    })
  } catch {
    return e.result ?? ''
  }
}

function toApiMessages(ents: ChatEntry[]): ChatMessage[] {
  const msgs: ChatMessage[] = []
  for (const e of ents) {
    if (e.kind === 'user' || e.kind === 'assistant') {
      msgs.push({ role: e.kind, content: e.text })
    } else if (e.kind === 'tool_call' && e.result !== null) {
      // Preserve the tool call + its result so the model still has it in
      // view on later turns. A null result means the stream was
      // interrupted before this tool call resolved -- there's nothing
      // valid to pair it with, so it's dropped rather than resent broken.
      msgs.push({
        role: 'tool_call',
        id: e.id,
        name: e.name,
        input: e.input,
        result: resultForApi(e),
      })
    }
  }
  return msgs
}

function applyEvent(prev: ChatEntry[], event: AiEvent): ChatEntry[] {
  switch (event.type) {
    case 'text_delta': {
      const last = prev[prev.length - 1]
      if (last?.kind === 'assistant') {
        return [
          ...prev.slice(0, -1),
          { ...last, text: last.text + event.delta },
        ]
      }
      return [
        ...prev,
        { kind: 'assistant', text: event.delta, streaming: true },
      ]
    }
    case 'tool_use_start':
      return [
        ...prev,
        {
          kind: 'tool_call',
          id: event.id,
          name: event.name,
          input: event.input,
          result: null,
        },
      ]
    case 'tool_result':
      return prev.map((e) =>
        e.kind === 'tool_call' && e.id === event.tool_use_id
          ? { ...e, result: event.content }
          : e,
      )
    case 'done':
      // Clear streaming on every assistant entry — after a proposal halt the last
      // entry is the tool call, so targeting only the last entry would leave the
      // assistant message stuck "streaming".
      return prev.map((e) =>
        e.kind === 'assistant' && e.streaming ? { ...e, streaming: false } : e,
      )
    case 'error': {
      const last = prev[prev.length - 1]
      if (last?.kind === 'assistant') {
        return [
          ...prev.slice(0, -1),
          { ...last, text: `⚠ ${event.message}`, streaming: false },
        ]
      }
      return [
        ...prev,
        { kind: 'assistant', text: `⚠ ${event.message}`, streaming: false },
      ]
    }
    default:
      return prev
  }
}

/** Owns the AI panel's conversation: entries/busy state, and the
 * streamChat + applyEvent round-trip for sending a new message or
 * continuing after a proposal is resolved. Session persistence (localStorage)
 * is deliberately not this hook's concern -- sendMessage/resolveAndContinue
 * return the final entries array once the stream settles so the caller can
 * act on it (e.g. AiPanel persists the session), since React state can't be
 * read back synchronously from here. */
export function useAiChat(initialEntries: ChatEntry[] = []) {
  const [entries, setEntries] = useState<ChatEntry[]>(initialEntries)
  const [busy, setBusy] = useState(false)

  // Streams one assistant turn from `msgs` and applies the resulting events.
  // Shared by sendMessage (a new user message) and resolveAndContinue (an
  // automatic continuation after a proposal is resolved) so both go through
  // the exact same request/response handling. Tracks the entries array
  // locally (alongside dispatching the same updates to React state) so the
  // final value is available synchronously at the end for the caller.
  async function runStream(msgs: ChatMessage[]): Promise<ChatEntry[]> {
    setBusy(true)
    let current: ChatEntry[] = []
    setEntries((prev) => {
      current = [...prev, { kind: 'assistant', text: '', streaming: true }]
      return current
    })
    try {
      for await (const event of streamChat(msgs)) {
        setEntries((prev) => {
          current = applyEvent(prev, event)
          return current
        })
        if (event.type === 'done' || event.type === 'error') break
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setEntries((prev) => {
        current = [
          ...prev.slice(0, -1),
          { kind: 'assistant', text: `Error: ${msg}`, streaming: false },
        ]
        return current
      })
    } finally {
      setBusy(false)
    }
    return current
  }

  async function sendMessage(text: string): Promise<ChatEntry[]> {
    const userEntry: UserEntry = { kind: 'user', text }
    const nextEntries = [...entries, userEntry]
    setEntries((prev) => [...prev, userEntry])
    return runStream(toApiMessages(nextEntries))
  }

  // Records the outcome(s) of one or more resolved proposals, then
  // automatically continues the conversation — the model gets a chance to
  // react (e.g. move on to the next step of a multi-part request) without
  // the user having to manually prompt it after every approval. This is a
  // deterministic continuation of the existing tool-round-trip mechanism
  // (see civex.server.routers.ai's proposal-halt comment), not something the
  // model is instructed to do on its own.
  async function resolveAndContinue(
    resolutions: ResolvedEntry[],
  ): Promise<ChatEntry[] | undefined> {
    if (busy) return undefined
    const updated = entries.map((e) => {
      if (e.kind !== 'tool_call') return e
      const r = resolutions.find((x) => x.id === e.id)
      return r ? { ...e, outcome: r.outcome, outcomeLabel: r.outcomeLabel } : e
    })
    setEntries(updated)
    return runStream(toApiMessages(updated))
  }

  return { entries, setEntries, busy, sendMessage, resolveAndContinue }
}
