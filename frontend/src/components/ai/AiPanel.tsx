import { useState } from 'react'
import { useAiSession } from '../../hooks/useAiSession'
import AiChatBody from './AiChatBody'
import { IconButton } from '../ui/IconButton'
import { History, Settings, ExternalLink, X, Sparkles } from '../ui/icons'

interface AiPanelProps {
  onClose: () => void
}

// Docked side panel — mounted only while open, inside a resizable split
// (see Layout.tsx) rather than as a fixed overlay, so it shares screen
// space with the current page instead of covering it. The full-page /ai
// tab (AiPage.tsx) is the same AiChatBody with different chrome around it.
//
// This is a landmark region, not a dialog: unlike the off-canvas nav
// drawer (which still uses useDialogA11y), the panel sits side-by-side
// with the main content rather than over it, so trapping focus or marking
// the rest of the page inert would make the split view it's meant to
// enable unusable with a keyboard.
export default function AiPanel({ onClose }: AiPanelProps) {
  const session = useAiSession()
  const [showSettings, setShowSettings] = useState(false)
  const [showHistory, setShowHistory] = useState(false)

  return (
    <div
      role="complementary"
      aria-label="AI assistant"
      className="h-full flex flex-col bg-canvas border-l border-border"
    >
      <div className="flex items-center gap-2 border-b border-border bg-canvas-subtle px-4 py-3">
        <Sparkles size={14} className="text-accent" />
        <span className="text-sm font-semibold text-fg">civex AI</span>
        <div className="flex-1" />
        <IconButton
          icon={History}
          aria-label={showHistory ? 'Back to chat' : 'Chat history'}
          aria-pressed={showHistory}
          className={showHistory ? 'text-accent' : ''}
          onClick={() => {
            setShowHistory((h) => !h)
            setShowSettings(false)
          }}
        />
        <IconButton
          icon={Settings}
          aria-label={showSettings ? 'Back to chat' : 'AI settings'}
          aria-pressed={showSettings}
          className={showSettings ? 'text-accent' : ''}
          onClick={() => {
            setShowSettings((s) => !s)
            setShowHistory(false)
          }}
        />
        <IconButton
          icon={ExternalLink}
          aria-label="Open in new tab"
          onClick={() => window.open('/ai', '_blank', 'noopener')}
        />
        <IconButton
          icon={X}
          aria-label="Close AI assistant"
          onClick={onClose}
        />
      </div>

      <AiChatBody
        session={session}
        showSettings={showSettings}
        showHistory={showHistory}
        onCloseSettings={() => setShowSettings(false)}
        onCloseHistory={() => setShowHistory(false)}
      />
    </div>
  )
}
