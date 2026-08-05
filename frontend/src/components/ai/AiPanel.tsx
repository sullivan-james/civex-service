import { useEffect, useRef, useState } from 'react'
import { useAiChat } from '../../hooks/useAiChat'
import type {
  ChatEntry,
  ResolvedEntry,
  StoredSession,
  ToolCallEntry,
  UserEntry,
} from '../../types/ai'
import AssistantText from './AssistantText'
import ApprovalBar from './ApprovalBar'
import BulkApprovalBar from './BulkApprovalBar'
import HistoryPane from './HistoryPane'
import SettingsPane from './SettingsPane'
import ToolCallRow from './ToolCallRow'
import { isPendingApproval } from './proposals'

// ---------------------------------------------------------------------------
// Session persistence helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

interface AiPanelProps {
  open: boolean
  onClose: () => void
}

export default function AiPanel({ open, onClose }: AiPanelProps) {
  // Restoring the most recent session on mount reads from localStorage once
  // and needs no reactive dependency, so it's a lazy useState initializer
  // rather than a mount-only useEffect calling setState (see
  // react-hooks/set-state-in-effect: effects should synchronize with
  // external systems, not synchronously set our own React state). Wrapped
  // in its own useState purely to compute it once -- useAiChat's initial
  // value argument is otherwise re-evaluated (though not re-used) on every
  // render.
  const [initialEntries] = useState<ChatEntry[]>(() => {
    const first = loadSessions()[0]
    return first
      ? first.entries.map((e) =>
          e.kind === 'assistant' ? { ...e, streaming: false } : e,
        )
      : []
  })
  const { entries, setEntries, busy, sendMessage, resolveAndContinue } =
    useAiChat(initialEntries)
  const [input, setInput] = useState('')
  const [showSettings, setShowSettings] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [fullscreen, setFullscreen] = useState(false)
  const [sessionId, setSessionId] = useState(
    () => loadSessions()[0]?.id ?? `${Date.now()}`,
  )
  const [sessions, setSessions] = useState<StoredSession[]>(() =>
    loadSessions(),
  )
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries])

  function startNewChat() {
    setEntries([])
    setInput('')
    setSessionId(`${Date.now()}`)
    setShowHistory(false)
  }

  function restoreSession(session: StoredSession) {
    setEntries(
      session.entries.map((e) =>
        e.kind === 'assistant' ? { ...e, streaming: false } : e,
      ),
    )
    setSessionId(session.id)
    setShowHistory(false)
  }

  function deleteSession(id: string, e: React.MouseEvent) {
    e.stopPropagation()
    setSessions((prev) => {
      const updated = prev.filter((s) => s.id !== id)
      saveSessions(updated)
      return updated
    })
  }

  // Persists the session as soon as a complete assistant response arrives.
  // Called directly wherever a stream settles (sendMessage/resolveAndContinue
  // return the final entries array once it does), not a useEffect watching
  // `entries` -- effects should synchronize with external systems, not
  // synchronously set our own React state (react-hooks/set-state-in-effect).
  // saveSessions() itself is still the external-system (localStorage) write;
  // setSessions updates our own in-memory mirror of it for the History pane.
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

  async function handleResolveAndContinue(resolutions: ResolvedEntry[]) {
    const finalEntries = await resolveAndContinue(resolutions)
    if (finalEntries) saveIfComplete(finalEntries)
  }

  async function handleSend() {
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    saveIfComplete(await sendMessage(text))
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const containerClass = fullscreen
    ? `fixed inset-0 flex flex-col bg-white z-50 ${open ? '' : 'hidden'}`
    : `fixed inset-y-0 right-0 w-[420px] flex flex-col bg-white border-l border-[#d0d7de] shadow-2xl z-50 ${open ? '' : 'hidden'}`

  const bodyClass = fullscreen
    ? 'flex-1 flex flex-col overflow-hidden max-w-3xl mx-auto w-full'
    : 'flex-1 flex flex-col overflow-hidden'

  // Every unresolved proposal from the thread, in chronological order. A
  // single turn can propose several changes at once (e.g. parallel tool
  // calls), so this is a list, not a single entry — each gets its own card
  // (keyed by id) rather than forcing one-at-a-time reverse-order approval.
  const pendingEntries: ToolCallEntry[] = busy
    ? []
    : entries.filter(
        (e): e is ToolCallEntry =>
          e.kind === 'tool_call' && isPendingApproval(e),
      )

  return (
    <div className={containerClass}>
      {/* Header */}
      <div className="flex items-center border-b border-[#d0d7de] bg-[#f6f8fa] px-4 py-3">
        <div
          className={`flex items-center gap-2 w-full ${fullscreen ? 'max-w-3xl mx-auto' : ''}`}
        >
          <span className="text-[#0969da]">✦</span>
          <span className="text-sm font-semibold text-[#1f2328]">civex AI</span>
          <div className="flex-1" />
          {/* History button */}
          <button
            onClick={() => {
              setShowHistory((h) => !h)
              setShowSettings(false)
            }}
            title={showHistory ? 'Back to chat' : 'Chat history'}
            className={`p-1 transition-colors ${showHistory ? 'text-[#0969da]' : 'text-[#656d76] hover:text-[#1f2328]'}`}
          >
            <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor">
              <path d="M1.643 3.143L.427 1.927A.25.25 0 0 0 0 2.104V5.75c0 .138.112.25.25.25h3.646a.25.25 0 0 0 .177-.427L2.715 4.215a6.5 6.5 0 1 1-1.18 4.458.75.75 0 1 0-1.493.154 8 8 0 1 0 1.6-5.684ZM8 5.25a.75.75 0 0 1 .75.75v2.69l1.28 1.28a.75.75 0 0 1-1.06 1.06L7.22 9.28A.75.75 0 0 1 7 8.75V6A.75.75 0 0 1 8 5.25Z" />
            </svg>
          </button>
          {/* Settings button */}
          <button
            onClick={() => {
              setShowSettings((s) => !s)
              setShowHistory(false)
            }}
            title={showSettings ? 'Back to chat' : 'AI settings'}
            className={`p-1 transition-colors ${showSettings ? 'text-[#0969da]' : 'text-[#656d76] hover:text-[#1f2328]'}`}
          >
            <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8 0a8.2 8.2 0 0 1 .701.031C9.444.095 9.99.645 9.99 1.311v.171a6.946 6.946 0 0 1 1.524.625l.121-.12a1.311 1.311 0 0 1 1.855 0l.354.353a1.311 1.311 0 0 1 0 1.855l-.12.121c.247.473.43.98.524 1.524h.171c.666 0 1.216.546 1.28 1.29A8.2 8.2 0 0 1 16 8a8.2 8.2 0 0 1-.031.701c-.064.744-.614 1.29-1.28 1.29h-.171a6.946 6.946 0 0 1-.524 1.524l.12.121a1.311 1.311 0 0 1 0 1.855l-.353.354a1.311 1.311 0 0 1-1.855 0l-.121-.12a6.946 6.946 0 0 1-1.524.524v.171c0 .666-.546 1.216-1.29 1.28A8.2 8.2 0 0 1 8 16a8.2 8.2 0 0 1-.701-.031c-.744-.064-1.29-.614-1.29-1.28v-.171a6.946 6.946 0 0 1-1.524-.524l-.121.12a1.311 1.311 0 0 1-1.855 0l-.354-.353a1.311 1.311 0 0 1 0-1.855l.12-.121A6.946 6.946 0 0 1 2.25 10.7h-.171c-.666 0-1.216-.546-1.28-1.29A8.2 8.2 0 0 1 0 8a8.2 8.2 0 0 1 .031-.701C.095 6.556.645 6.01 1.311 6.01h.171a6.946 6.946 0 0 1 .524-1.524l-.12-.121a1.311 1.311 0 0 1 0-1.855l.353-.354a1.311 1.311 0 0 1 1.855 0l.121.12A6.946 6.946 0 0 1 5.74 1.77h-.17v-.17c0-.666.545-1.216 1.29-1.28A8.233 8.233 0 0 1 8 .001Zm-.5 4.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z" />
            </svg>
          </button>
          {/* Fullscreen toggle */}
          <button
            onClick={() => setFullscreen((f) => !f)}
            title={fullscreen ? 'Exit full screen' : 'Full screen'}
            className="p-1 text-[#656d76] hover:text-[#1f2328] transition-colors"
          >
            {fullscreen ? (
              <svg
                width="15"
                height="15"
                viewBox="0 0 16 16"
                fill="currentColor"
              >
                <path d="M5.5 0a.5.5 0 0 1 .5.5v4a.5.5 0 0 1-.5.5h-4a.5.5 0 0 1 0-1H5V.5a.5.5 0 0 1 .5-.5Zm5 0a.5.5 0 0 1 .5.5V5h3.5a.5.5 0 0 1 0 1h-4a.5.5 0 0 1-.5-.5v-4a.5.5 0 0 1 .5-.5ZM0 10.5a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 .5.5v4a.5.5 0 0 1-1 0V11H.5a.5.5 0 0 1-.5-.5Zm11 0a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 0 1H12v3.5a.5.5 0 0 1-1 0v-4Z" />
              </svg>
            ) : (
              <svg
                width="15"
                height="15"
                viewBox="0 0 16 16"
                fill="currentColor"
              >
                <path d="M1.5 1h4a.5.5 0 0 1 0 1H2v3.5a.5.5 0 0 1-1 0v-4a.5.5 0 0 1 .5-.5Zm9 0h4a.5.5 0 0 1 .5.5v4a.5.5 0 0 1-1 0V2h-3.5a.5.5 0 0 1 0-1ZM1 10.5a.5.5 0 0 1 .5-.5.5.5 0 0 1 .5.5V14h3.5a.5.5 0 0 1 0 1h-4a.5.5 0 0 1-.5-.5v-4Zm13 0v4a.5.5 0 0 1-.5.5h-4a.5.5 0 0 1 0-1H14v-3.5a.5.5 0 0 1 .5-.5.5.5 0 0 1 .5.5Z" />
              </svg>
            )}
          </button>
          <button
            onClick={onClose}
            className="text-[#656d76] hover:text-[#1f2328] transition-colors p-1"
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
              <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
            </svg>
          </button>
        </div>
      </div>

      {/* Body — centered in fullscreen */}
      <div className={bodyClass}>
        {/* Settings pane */}
        {showSettings && (
          <div className="flex-1 overflow-y-auto">
            <SettingsPane onSaved={() => setShowSettings(false)} />
          </div>
        )}

        {/* History pane */}
        {showHistory && (
          <HistoryPane
            sessions={sessions}
            onRestore={restoreSession}
            onDelete={deleteSession}
            onNewChat={startNewChat}
          />
        )}

        {/* Messages */}
        <div
          className={`flex-1 overflow-y-auto px-4 py-4 space-y-3 ${showSettings || showHistory ? 'hidden' : ''}`}
        >
          {entries.length === 0 && (
            <div className="text-center py-12 text-[#656d76] text-sm space-y-3">
              <div className="text-3xl">✦</div>
              <p className="font-medium text-[#1f2328]">Ask me anything</p>
              <div className="text-xs space-y-2 text-left max-w-[280px] mx-auto">
                <p className="text-[#656d76]">Try:</p>
                {[
                  'How many records do I have?',
                  'What field types does civex support?',
                  'Create a workflow that extracts dates from filenames',
                  'Write a plugin that calls an external API',
                ].map((s) => (
                  <button
                    key={s}
                    onClick={() => {
                      setInput(s)
                      textareaRef.current?.focus()
                    }}
                    className="block w-full text-left px-3 py-2 rounded-md border border-[#d0d7de] bg-white hover:bg-[#f6f8fa] text-[#1f2328] transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {entries.map((entry, i) => {
            if (entry.kind === 'user') {
              return (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-tr-sm px-4 py-2 bg-[#24292f] text-white text-sm whitespace-pre-wrap">
                    {entry.text}
                  </div>
                </div>
              )
            }
            if (entry.kind === 'assistant') {
              return (
                <div key={i} className="flex justify-start">
                  <div className="max-w-[95%]">
                    <AssistantText
                      text={entry.text}
                      streaming={entry.streaming}
                    />
                  </div>
                </div>
              )
            }
            return <ToolCallRow key={i} entry={entry} />
          })}

          <div ref={bottomRef} />
        </div>

        {/* Input (or the approval card(s) when proposed changes await the user) */}
        <div
          className={`border-t border-[#d0d7de] p-3 bg-[#f6f8fa] ${showSettings || showHistory ? 'hidden' : ''}`}
        >
          {pendingEntries.length > 0 ? (
            <div className="space-y-2">
              <BulkApprovalBar
                entries={pendingEntries}
                onResolve={handleResolveAndContinue}
              />
              <div
                className={`space-y-2 ${pendingEntries.length > 2 ? 'max-h-64 overflow-y-auto pr-1' : ''}`}
              >
                {pendingEntries.map((e) => (
                  <ApprovalBar
                    key={e.id}
                    entry={e}
                    onResolve={handleResolveAndContinue}
                  />
                ))}
              </div>
            </div>
          ) : (
            <>
              <div className="flex gap-2 items-end">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask about your data or describe a workflow…"
                  rows={2}
                  disabled={busy}
                  className="flex-1 resize-none rounded-md border border-[#d0d7de] bg-white px-3 py-2 text-sm text-[#1f2328] placeholder:text-[#adbac7] focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da] disabled:opacity-50"
                />
                <button
                  onClick={handleSend}
                  disabled={busy || !input.trim()}
                  className="flex-shrink-0 px-3 py-2 rounded-md bg-[#0969da] text-white text-sm font-medium hover:bg-[#0860ca] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {busy ? (
                    <svg
                      className="animate-spin w-4 h-4"
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
                  ) : (
                    <svg
                      width="16"
                      height="16"
                      viewBox="0 0 16 16"
                      fill="currentColor"
                    >
                      <path d="M1.5 2.75a.75.75 0 0 1 .75-.75h.75a.75.75 0 0 1 0 1.5H3V7h10V3.5H12a.75.75 0 0 1 0-1.5h.75a.75.75 0 0 1 .75.75v5a.75.75 0 0 1-.75.75H9.56l1.22 1.22a.75.75 0 0 1-1.06 1.06l-2.5-2.5a.75.75 0 0 1 0-1.06l2.5-2.5a.75.75 0 1 1 1.06 1.06L9.56 7.5h2.69V8H3V7.5h2.69L4.47 6.28a.75.75 0 0 1 1.06-1.06l2.5 2.5a.75.75 0 0 1 0 1.06l-2.5 2.5a.75.75 0 0 1-1.06-1.06L5.69 8.5H3V8H3V3.5H2.25a.75.75 0 0 1-.75-.75Z" />
                    </svg>
                  )}
                </button>
              </div>
              <p className="mt-2 text-xs text-[#adbac7] text-center">
                Enter to send · Shift+Enter for new line
              </p>
            </>
          )}
        </div>
      </div>
      {/* /body */}
    </div>
  )
}
