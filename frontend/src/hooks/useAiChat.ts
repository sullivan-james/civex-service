import { useEffect, useRef, useState } from 'react'
import { type AiEvent, type ChatMessage, streamChat } from '../api/ai'
import { isPendingApproval } from '../components/ai/proposals'
import type {
  ChatEntry,
  ResolvedEntry,
  ToolCallEntry,
  UserEntry,
} from '../types/ai'

// No event (including the first byte of a response) for this long is
// treated as a dead connection rather than left to spin forever.
const STALL_TIMEOUT_MS = 45_000

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
      const errored = {
        kind: 'assistant' as const,
        text: event.message,
        streaming: false,
        error: true,
      }
      if (last?.kind === 'assistant') return [...prev.slice(0, -1), errored]
      return [...prev, errored]
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
 * read back synchronously from here.
 *
 * Robustness: each stream runs behind an AbortController so a caller can
 * cancel() a hung request, a stall timer aborts automatically if the server
 * goes silent mid-stream, and state updates from an in-flight stream are
 * dropped once the owning component unmounts. */
export function useAiChat(initialEntries: ChatEntry[] = []) {
  const [entries, setEntries] = useState<ChatEntry[]>(initialEntries)
  const [busy, setBusy] = useState(false)
  const controllerRef = useRef<AbortController | null>(null)
  const abortReasonRef = useRef<'user' | 'timeout' | null>(null)
  const isMountedRef = useRef(true)

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      controllerRef.current?.abort()
    }
  }, [])

  function safeSetEntries(
    updater: ChatEntry[] | ((prev: ChatEntry[]) => ChatEntry[]),
  ) {
    if (isMountedRef.current) setEntries(updater)
  }

  /** Aborts the in-flight stream, if any. The partial assistant reply stays
   * on screen (just marked no-longer-streaming) rather than being replaced
   * with an error — a deliberate stop isn't a failure. */
  function cancel() {
    if (!controllerRef.current) return
    abortReasonRef.current = 'user'
    controllerRef.current.abort()
  }

  // Streams one assistant turn from `msgs` and applies the resulting events.
  // Shared by sendMessage (a new user message) and resolveAndContinue (an
  // automatic continuation after a proposal is resolved) so both go through
  // the exact same request/response handling. Tracks the entries array
  // locally (alongside dispatching the same updates to React state) so the
  // final value is available synchronously at the end for the caller.
  async function runStream(msgs: ChatMessage[]): Promise<ChatEntry[]> {
    const controller = new AbortController()
    controllerRef.current = controller
    abortReasonRef.current = null
    setBusy(true)
    let current: ChatEntry[] = []
    safeSetEntries((prev) => {
      current = [...prev, { kind: 'assistant', text: '', streaming: true }]
      return current
    })

    let stallTimer: ReturnType<typeof setTimeout> | undefined
    const armStallTimer = () => {
      clearTimeout(stallTimer)
      stallTimer = setTimeout(() => {
        abortReasonRef.current = 'timeout'
        controller.abort()
      }, STALL_TIMEOUT_MS)
    }

    try {
      armStallTimer()
      for await (const event of streamChat(msgs, controller.signal)) {
        armStallTimer()
        safeSetEntries((prev) => {
          current = applyEvent(prev, event)
          return current
        })
        if (event.type === 'done' || event.type === 'error') break
      }
    } catch (err) {
      if (abortReasonRef.current === 'user') {
        safeSetEntries((prev) => {
          current = prev.map((e) =>
            e.kind === 'assistant' && e.streaming
              ? { ...e, streaming: false }
              : e,
          )
          return current
        })
      } else {
        const message =
          abortReasonRef.current === 'timeout'
            ? 'The assistant stopped responding. Try again.'
            : err instanceof Error
              ? err.message
              : String(err)
        safeSetEntries((prev) => {
          const last = prev[prev.length - 1]
          const withoutStreaming =
            last?.kind === 'assistant' && last.streaming
              ? prev.slice(0, -1)
              : prev
          current = [
            ...withoutStreaming,
            { kind: 'assistant', text: message, streaming: false, error: true },
          ]
          return current
        })
      }
    } finally {
      clearTimeout(stallTimer)
      controllerRef.current = null
      setBusy(false)
    }
    return current
  }

  async function sendMessage(text: string): Promise<ChatEntry[]> {
    const userEntry: UserEntry = { kind: 'user', text }
    const nextEntries = [...entries, userEntry]
    safeSetEntries((prev) => [...prev, userEntry])
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
    // A single turn can propose several changes at once, each rendered as its
    // own card (see AiPanel's pendingEntries). Only auto-continue once every
    // one of them has an outcome -- resolving just the first must not send a
    // half-resolved turn to the model while the rest still await a click
    // (the model would see them stuck at "proposed" forever and just move
    // on, so those changes would never actually get applied).
    const stillPending = updated.some(
      (e): e is ToolCallEntry => e.kind === 'tool_call' && isPendingApproval(e),
    )
    if (stillPending) return updated
    return runStream(toApiMessages(updated))
  }

  return { entries, setEntries, busy, sendMessage, resolveAndContinue, cancel }
}
