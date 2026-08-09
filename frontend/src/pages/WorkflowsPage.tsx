import { useState } from 'react'
import { usePlugins } from '../hooks/usePlugins'
import { Page, Button } from '../components/ui'
import { WorkflowRunModal } from '../components/workflows/WorkflowRunModal'
import { WorkflowEditorModal } from '../components/workflows/WorkflowEditorModal'
import { WorkflowsPanel } from '../components/workflows/WorkflowsPanel'
import { PluginsPanel } from '../components/workflows/PluginsPanel'
import { ContainerPluginsPanel } from '../components/workflows/ContainerPluginsPanel'
import type { Workflow } from '../api/workflows'

export default function WorkflowsPage() {
  const { data: pluginList } = usePlugins()

  const [editor, setEditor] = useState<{ stem: string; isNew: boolean } | null>(
    null,
  )
  const [runTarget, setRunTarget] = useState<Workflow | null>(null)

  return (
    <Page
      title="Workflows"
      description="YAML workflow definitions in .civex/workflows/"
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
        onEdit={(wf) => setEditor({ stem: wf.stem, isNew: false })}
      />

      <PluginsPanel />

      <ContainerPluginsPanel />

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
