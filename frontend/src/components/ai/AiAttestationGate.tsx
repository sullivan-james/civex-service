import { useState, type ReactNode } from 'react'
import { Button, Modal, ModalBody, ModalFooter, ModalHeader } from '../ui'
import { Sparkles } from '../ui/icons'

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
  children: ReactNode
}

// One-time, client-side-only consent gate wrapping any AI surface (the
// docked panel, the standalone /ai tab). Once acknowledged, this always
// renders `children` -- same as if this wrapper didn't exist. Only the
// pre-acknowledgment path early-returns based on `open`, since there's
// nothing to keep mounted yet.
export default function AiAttestationGate({
  open,
  onClose,
  children,
}: AiAttestationGateProps) {
  const [acked, setAcked] = useState(hasAcknowledged)

  if (acked) return <>{children}</>

  if (!open) return null

  return (
    <Modal onClose={onClose}>
      <ModalHeader>
        <span className="inline-flex items-center gap-2">
          <Sparkles size={18} className="text-accent" />
          Before you use the AI assistant
        </span>
      </ModalHeader>
      <ModalBody className="text-sm text-fg space-y-2">
        <p>
          Depending on how it&apos;s configured, the AI assistant sends
          conversation content — including schema, record, and workflow data it
          looks up on your behalf — to a third-party API (Anthropic, OpenRouter,
          or another provider you&apos;ve configured). That provider&apos;s own
          data handling and retention terms apply to whatever gets sent.
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
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>Not now</Button>
        <Button
          variant="primary"
          onClick={() => {
            acknowledge()
            setAcked(true)
          }}
        >
          I understand, continue
        </Button>
      </ModalFooter>
    </Modal>
  )
}
