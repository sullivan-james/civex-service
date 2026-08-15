import { useState } from 'react'
import { useAiChat } from './useAiChat'
import type {
  ChatEntry,
  ResolvedEntry,
  StoredSession,
  UserEntry,
} from '../types/ai'

const SESSIONS_KEY = 'civex-ai-sessions'
const MAX_SESSIONS = 15

function loadSessions(): StoredSession[] {
  try {
    return JSON.parse(localStorage.getItem(SESSIONS_KEY) ?? '[]')
  } catch {
    return []
  }
}

function saveSessions(sessions: StoredSession[]): void {
  try {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions))
  } catch {
    /* quota exceeded */
  }
}

/** Owns everything the AI chat UI needs beyond the raw model stream: the
 * localStorage-backed session list (History pane), which session is active,
 * and turning a settled stream into a saved session. Kept separate from
 * useAiChat so that hook stays focused purely on the network/stream
 * concern — this is what both the docked panel and the standalone /ai tab
 * mount, so a chat started in one and revisited from the other picks up
 * from the same saved sessions. */
export function useAiSession() {
  const [initialEntries] = useState<ChatEntry[]>(() => {
    const first = loadSessions()[0]
    return first
      ? first.entries.map((e) =>
          e.kind === 'assistant' ? { ...e, streaming: false } : e,
        )
      : []
  })
  const chat = useAiChat(initialEntries)
  const [sessionId, setSessionId] = useState(
    () => loadSessions()[0]?.id ?? `${Date.now()}`,
  )
  const [sessions, setSessions] = useState<StoredSession[]>(() =>
    loadSessions(),
  )

  function startNewChat() {
    chat.setEntries([])
    setSessionId(`${Date.now()}`)
  }

  function restoreSession(session: StoredSession) {
    chat.setEntries(
      session.entries.map((e) =>
        e.kind === 'assistant' ? { ...e, streaming: false } : e,
      ),
    )
    setSessionId(session.id)
  }

  function deleteSession(
    id: string,
    e: React.MouseEvent | React.KeyboardEvent,
  ) {
    e.stopPropagation()
    setSessions((prev) => {
      const updated = prev.filter((s) => s.id !== id)
      saveSessions(updated)
      return updated
    })
  }

  // Persists the session as soon as a complete assistant response arrives.
  function saveIfComplete(finalEntries: ChatEntry[]) {
    const hasComplete = finalEntries.some(
      (e) => e.kind === 'assistant' && !e.streaming,
    )
    if (!hasComplete) return
    const firstUser =
      (finalEntries.find((e) => e.kind === 'user') as UserEntry | undefined)
        ?.text ?? ''
    const title = firstUser.slice(0, 70) || 'Chat'
    setSessions((prev) => {
      const without = prev.filter((s) => s.id !== sessionId)
      const updated = [
        {
          id: sessionId,
          title,
          createdAt: new Date().toISOString(),
          entries: finalEntries,
        },
        ...without,
      ].slice(0, MAX_SESSIONS)
      saveSessions(updated)
      return updated
    })
  }

  async function sendMessage(text: string) {
    saveIfComplete(await chat.sendMessage(text))
  }

  async function resolveAndContinue(resolutions: ResolvedEntry[]) {
    const finalEntries = await chat.resolveAndContinue(resolutions)
    if (finalEntries) saveIfComplete(finalEntries)
  }

  return {
    entries: chat.entries,
    busy: chat.busy,
    cancel: chat.cancel,
    sendMessage,
    resolveAndContinue,
    sessions,
    startNewChat,
    restoreSession,
    deleteSession,
  }
}
