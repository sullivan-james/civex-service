import { useState } from 'react'
import AiPanel from './AiPanel'

// Bump this if the attestation's substance changes materially (e.g. a new
// data-sharing risk) -- a new key means everyone sees it again once, rather
// than silently grandfathering existing acknowledgments under new terms.
const ACK_KEY = 'civex-ai-attestation-ack-v1'

function hasAcknowledged(): boolean {
  try {
    return localStorage.getItem(ACK_KEY) === 'true'
  } catch {
    return false
  }
}

function acknowledge(): void {
  try {
    localStorage.setItem(ACK_KEY, 'true')
  } catch {
    /* quota exceeded / private browsing -- attestation just re-shows next time */
  }
}

interface AiAttestationGateProps {
  open: boolean
  onClose: () => void
}

// Wraps AiPanel with a one-time, client-side-only consent gate. Once
// acknowledged, this always renders <AiPanel open={open} .../> -- same as
// if this wrapper didn't exist -- so AiPanel's own "stay mounted, toggle via
// CSS" behavior (see its containerClass comment) is preserved for the rest
// of the session. Only the pre-acknowledgment path early-returns based on
// `open`, since there's nothing to keep mounted yet.
export default function AiAttestationGate({
  open,
  onClose,
}: AiAttestationGateProps) {
  const [acked, setAcked] = useState(hasAcknowledged)

  if (acked) {
    return <AiPanel open={open} onClose={onClose} />
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="max-w-md w-full rounded-lg bg-white shadow-xl p-6 space-y-4">
        <div className="flex items-center gap-2">
          <span className="text-accent text-xl">✦</span>
          <h2 className="text-base font-semibold text-fg">
            Before you use the AI assistant
          </h2>
        </div>
        <div className="text-sm text-fg space-y-2">
          <p>
            Depending on how it&apos;s configured, the AI assistant sends
            conversation content — including schema, record, and workflow data
            it looks up on your behalf — to a third-party API (Anthropic,
            OpenRouter, or another provider you&apos;ve configured). That
            provider&apos;s own data handling and retention terms apply to
            whatever gets sent.
          </p>
          <p>
            If it&apos;s configured to use a local Ollama model instead, nothing
            leaves this machine — check AI settings to see which provider is
            currently active.
          </p>
          <p className="text-fg-muted text-xs">
            Review this project&apos;s data-handling policies under{' '}
            <a href="/legal" className="text-accent hover:underline">
              Licenses &amp; policies
            </a>{' '}
            before enabling this with sensitive data.
          </p>
        </div>
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded border border-border text-sm text-fg-muted hover:bg-canvas-subtle"
          >
            Not now
          </button>
          <button
            onClick={() => {
              acknowledge()
              setAcked(true)
            }}
            className="px-3 py-1.5 rounded bg-accent text-white text-sm font-medium hover:bg-accent-emphasis"
          >
            I understand, continue
          </button>
        </div>
      </div>
    </div>
  )
}
