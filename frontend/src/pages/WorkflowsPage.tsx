import { useState } from 'react'
import { usePlugins } from '../hooks/usePlugins'
import { Page, Button } from '../components/ui'
import { WorkflowRunModal } from '../components/workflows/WorkflowRunModal'
import { WorkflowSummaryModal } from '../components/workflows/WorkflowSummaryModal'
import { WorkflowsPanel } from '../components/workflows/WorkflowsPanel'
import type { Workflow } from '../api/workflows'

export default function WorkflowsPage() {
  const { data: pluginList } = usePlugins()

  const [summaryTarget, setSummaryTarget] = useState<Workflow | null>(null)
  const [runTarget, setRunTarget] = useState<Workflow | null>(null)

  return (
    <Page
      title="Workflows"
      info="Automations that run when records are created or updated."
      action={
        <Button
          to="/workflows/new"
          target="_blank"
          rel="opener"
          variant="primary"
        >
          + New workflow
        </Button>
      }
    >
      <WorkflowsPanel
        onRun={(wf) => setRunTarget(wf)}
        onView={(wf) => setSummaryTarget(wf)}
      />

      {summaryTarget && (
        <WorkflowSummaryModal
          workflow={summaryTarget}
          plugins={pluginList ?? []}
          onClose={() => setSummaryTarget(null)}
        />
      )}

      {runTarget && (
        <WorkflowRunModal
          workflow={runTarget}
          onClose={() => setRunTarget(null)}
        />
      )}
    </Page>
  )
}
