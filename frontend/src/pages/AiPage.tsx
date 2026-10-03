import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useAiSession } from '../hooks/useAiSession'
import AiChatBody from '../components/ai/AiChatBody'
import AiAttestationGate from '../components/ai/AiAttestationGate'
import { Button, Page } from '../components/ui'
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
        action={
          <div className="flex items-center gap-1">
            <Button
              size="sm"
              variant={showHistory ? 'link' : 'ghost'}
              aria-pressed={showHistory}
              onClick={() => {
                setShowHistory((h) => !h)
                setShowSettings(false)
              }}
            >
              <History size={14} /> History
            </Button>
            <Button
              size="sm"
              variant={showSettings ? 'link' : 'ghost'}
              aria-pressed={showSettings}
              onClick={() => {
                setShowSettings((s) => !s)
                setShowHistory(false)
              }}
            >
              <Settings size={14} /> Settings
            </Button>
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
