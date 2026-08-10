import { useState } from 'react'
import { usePlugins } from '../hooks/usePlugins'
import { Page, Button } from '../components/ui'
import { WorkflowRunModal } from '../components/workflows/WorkflowRunModal'
import { WorkflowEditorModal } from '../components/workflows/WorkflowEditorModal'
import { WorkflowSummaryModal } from '../components/workflows/WorkflowSummaryModal'
import { WorkflowsPanel } from '../components/workflows/WorkflowsPanel'
import type { Workflow } from '../api/workflows'

export default function WorkflowsPage() {
  const { data: pluginList } = usePlugins()

  const [summaryTarget, setSummaryTarget] = useState<Workflow | null>(null)
  const [editor, setEditor] = useState<{ stem: string; isNew: boolean } | null>(
    null,
  )
  const [runTarget, setRunTarget] = useState<Workflow | null>(null)

  return (
    <Page
      title="Workflows"
      description="Automations that run when records are created or updated. Plugins live under Advanced."
      action={
        <Button
          variant="primary"
          size="sm"
          onClick={() => setEditor({ stem: 'new-workflow', isNew: true })}
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
          onEditYaml={() => {
            setEditor({ stem: summaryTarget.stem, isNew: false })
            setSummaryTarget(null)
          }}
        />
      )}

      {editor && (
        <WorkflowEditorModal
          stem={editor.stem}
          isNew={editor.isNew}
          onClose={() => setEditor(null)}
          plugins={pluginList ?? []}
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
