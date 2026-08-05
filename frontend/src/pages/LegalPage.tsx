import { useState } from 'react'
import { useLicense, usePolicies } from '../hooks/useLegal'
import { LoadingState, ErrorState } from '../components/ui'
import { ChevronUp, ChevronDown } from '../components/ui/icons'
import { errorMessage } from '../lib/errors'

function LicenseSection() {
  const { data, isLoading, error } = useLicense()
  const [expanded, setExpanded] = useState(false)

  if (isLoading) return <LoadingState />
  if (error || !data)
    return (
      <ErrorState
        message={error ? errorMessage(error) : 'Failed to load license'}
      />
    )

  return (
    <div className="border border-border rounded-md bg-canvas p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-fg">Software license</p>
        <button
          onClick={() => setExpanded((e) => !e)}
          className="text-xs text-accent hover:underline"
        >
          {expanded ? 'Collapse' : 'Show full text'}
        </button>
      </div>
      <pre
        className={`text-xs font-mono text-fg-muted whitespace-pre-wrap ${expanded ? '' : 'max-h-24 overflow-hidden'}`}
      >
        {data.text}
      </pre>
    </div>
  )
}

function PoliciesSection() {
  const { data: policies, isLoading, error } = usePolicies()
  const [openStem, setOpenStem] = useState<string | null>(null)

  if (isLoading) return <LoadingState />
  if (error || !policies)
    return (
      <ErrorState
        message={error ? errorMessage(error) : 'Failed to load policies'}
      />
    )

  if (policies.length === 0) {
    return (
      <p className="text-sm text-fg-muted italic">
        No policy documents configured. Add markdown files to{' '}
        <span className="font-mono text-xs">_civex/policies/</span> to have them
        show up here.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {policies.map((p) => {
        const open = openStem === p.stem
        return (
          <div
            key={p.stem}
            className="border border-border rounded-md bg-canvas"
          >
            <button
              onClick={() => setOpenStem(open ? null : p.stem)}
              className="w-full flex items-center justify-between px-4 py-3 text-left"
            >
              <span className="text-sm font-medium text-fg">{p.title}</span>
              <span className="text-xs text-fg-muted">
                {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              </span>
            </button>
            {open && (
              <div className="border-t border-border px-4 py-3 bg-canvas-subtle">
                <pre className="text-xs font-mono text-fg whitespace-pre-wrap">
                  {p.content}
                </pre>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default function LegalPage() {
  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-xl font-semibold text-fg">
          Licenses &amp; Policies
        </h1>
        <p className="text-sm text-fg-muted mt-0.5">
          The software license for this build, plus any data/governance policies
          this deployment has documented.
        </p>
      </div>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold text-fg">License</h2>
        <LicenseSection />
      </div>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold text-fg">Policies</h2>
        <PoliciesSection />
      </div>
    </div>
  )
}
