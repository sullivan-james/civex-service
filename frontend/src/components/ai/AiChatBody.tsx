import { useEffect, useRef, useState } from 'react'
import type { useAiSession } from '../../hooks/useAiSession'
import type { ToolCallEntry } from '../../types/ai'
import AssistantText from './AssistantText'
import ApprovalBar from './ApprovalBar'
import BulkApprovalBar from './BulkApprovalBar'
import HistoryPane from './HistoryPane'
import SettingsPane from './SettingsPane'
import ToolCallRow from './ToolCallRow'
import { isPendingApproval } from './proposals'
import { Field, Textarea } from '../ui'
import { Sparkles, Send, Square } from '../ui/icons'

const SUGGESTIONS = [
  'How many records do I have?',
  'What field types does civex support?',
  'Create a workflow that extracts dates from filenames',
  'Write a plugin that calls an external API',
]

interface AiChatBodyProps {
  session: ReturnType<typeof useAiSession>
  showSettings: boolean
  showHistory: boolean
  onCloseSettings: () => void
  onCloseHistory: () => void
  /** The full-page /ai tab centers content in a readable column; the
   * docked side panel fills its (narrower) width edge-to-edge instead. */
  centered?: boolean
}

// The chat surface itself — messages, input, and the settings/history
// sub-panes — shared verbatim between the docked side panel (AiPanel) and
// the standalone full-page tab (AiPage). Only the chrome around it (header,
// container sizing) differs between the two.
export default function AiChatBody({
  session,
  showSettings,
  showHistory,
  onCloseSettings,
  onCloseHistory,
  centered,
}: AiChatBodyProps) {
  const {
    entries,
    busy,
    cancel,
    sendMessage,
    resolveAndContinue,
    sessions,
    startNewChat,
    restoreSession,
    deleteSession,
  } = session
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries])

  async function handleSend() {
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    await sendMessage(text)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

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

  const wrapClass = centered ? 'max-w-3xl mx-auto w-full' : ''

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {showSettings && (
        <div className="flex-1 overflow-y-auto">
          <div className={wrapClass}>
            <SettingsPane onSaved={onCloseSettings} />
          </div>
        </div>
      )}

      {showHistory && (
        <div className={`flex-1 min-h-0 flex flex-col ${wrapClass}`}>
          <HistoryPane
            sessions={sessions}
            onRestore={(s) => {
              restoreSession(s)
              onCloseHistory()
            }}
            onDelete={deleteSession}
            onNewChat={() => {
              startNewChat()
              onCloseHistory()
            }}
          />
        </div>
      )}

      <div
        className={`flex-1 overflow-y-auto px-4 py-4 space-y-3 ${showSettings || showHistory ? 'hidden' : ''}`}
      >
        <div className={`space-y-3 ${wrapClass}`}>
          {entries.length === 0 && (
            <div className="text-center py-12 text-fg-muted text-sm space-y-3">
              <Sparkles size={28} className="mx-auto" />
              <p className="font-medium text-fg">Ask me anything</p>
              <div className="text-xs space-y-2 text-left max-w-[280px] mx-auto">
                <p className="text-fg-muted">Try:</p>
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => {
                      setInput(s)
                      textareaRef.current?.focus()
                    }}
                    className="block w-full text-left px-3 py-2 rounded-md border border-border bg-canvas hover:bg-canvas-subtle text-fg transition-colors"
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
                  <div className="max-w-[85%] rounded-2xl rounded-tr-sm px-4 py-2 bg-nav-bg text-nav-fg text-sm whitespace-pre-wrap">
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
                      error={entry.error}
                    />
                  </div>
                </div>
              )
            }
            return <ToolCallRow key={i} entry={entry} />
          })}

          <div ref={bottomRef} />
        </div>
      </div>

      <div
        className={`border-t border-border p-3 bg-canvas-subtle ${showSettings || showHistory ? 'hidden' : ''}`}
      >
        <div className={wrapClass}>
          {pendingEntries.length > 0 ? (
            <div className="space-y-2">
              <BulkApprovalBar
                entries={pendingEntries}
                onResolve={resolveAndContinue}
              />
              <div
                className={`space-y-2 ${pendingEntries.length > 2 ? 'max-h-64 overflow-y-auto pr-1' : ''}`}
              >
                {pendingEntries.map((e) => (
                  <ApprovalBar
                    key={e.id}
                    entry={e}
                    onResolve={resolveAndContinue}
                  />
                ))}
              </div>
            </div>
          ) : (
            <>
              <div className="flex gap-2 items-end">
                <Field label="Message" hideLabel className="flex-1">
                  <Textarea
                    ref={textareaRef}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Ask about your data or describe a workflow…"
                    rows={2}
                    disabled={busy}
                    className="resize-none"
                  />
                </Field>
                <button
                  onClick={busy ? cancel : handleSend}
                  disabled={!busy && !input.trim()}
                  title={busy ? 'Stop generating' : 'Send'}
                  className="flex-shrink-0 px-3 py-2 rounded-md bg-accent text-fg-on-emphasis text-sm font-medium hover:bg-accent-emphasis disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {busy ? (
                    <Square size={16} fill="currentColor" />
                  ) : (
                    <Send size={16} />
                  )}
                </button>
              </div>
              <p className="mt-2 text-xs text-fg-subtle text-center">
                {busy
                  ? 'Generating… click stop to cancel'
                  : 'Enter to send · Shift+Enter for new line'}
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
