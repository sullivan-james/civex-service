import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useAiSession } from '../hooks/useAiSession'
import AiChatBody from '../components/ai/AiChatBody'
import AiAttestationGate from '../components/ai/AiAttestationGate'
import { Page } from '../components/ui'
import { History, Settings } from '../components/ui/icons'

// Standalone full-page mount of the AI assistant, reached via "Open in new
// tab" on the docked panel (see AiPanel.tsx) or by navigating to /ai
// directly. Same AiChatBody as the docked panel — sessions are shared
// through the same localStorage-backed history, so a chat started in one
// place is visible from the other — just with page chrome instead of a
// side-panel header.
export default function AiPage() {
  const navigate = useNavigate()
  const session = useAiSession()
  const [showSettings, setShowSettings] = useState(false)
  const [showHistory, setShowHistory] = useState(false)

  return (
    <AiAttestationGate open onClose={() => navigate('/')}>
      <Page
        title="AI Assistant"
        description="Ask about your data or describe a workflow to build."
        action={
          <div className="flex items-center gap-1">
            <button
              onClick={() => {
                setShowHistory((h) => !h)
                setShowSettings(false)
              }}
              title={showHistory ? 'Back to chat' : 'Chat history'}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium border transition-colors ${
                showHistory
                  ? 'border-accent text-accent bg-accent-subtle'
                  : 'border-border text-fg-muted hover:text-fg hover:bg-canvas-subtle'
              }`}
            >
              <History size={14} /> History
            </button>
            <button
              onClick={() => {
                setShowSettings((s) => !s)
                setShowHistory(false)
              }}
              title={showSettings ? 'Back to chat' : 'AI settings'}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium border transition-colors ${
                showSettings
                  ? 'border-accent text-accent bg-accent-subtle'
                  : 'border-border text-fg-muted hover:text-fg hover:bg-canvas-subtle'
              }`}
            >
              <Settings size={14} /> Settings
            </button>
          </div>
        }
      >
        <div
          className="rounded-lg border border-border overflow-hidden flex flex-col"
          style={{ height: 'calc(100vh - 220px)' }}
        >
          <AiChatBody
            session={session}
            showSettings={showSettings}
            showHistory={showHistory}
            onCloseSettings={() => setShowSettings(false)}
            onCloseHistory={() => setShowHistory(false)}
            centered
          />
        </div>
      </Page>
    </AiAttestationGate>
  )
}
