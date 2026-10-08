import { useState } from 'react'
import { usePlugins } from '../hooks/usePlugins'
import { Page, Button, TabNav, TabPanel, useTabParam } from '../components/ui'
import { LibraryPanel } from '../components/workflows/LibraryPanel'
import { WorkflowRunModal } from '../components/workflows/WorkflowRunModal'
import { WorkflowSummaryModal } from '../components/workflows/WorkflowSummaryModal'
import { WorkflowsPanel } from '../components/workflows/WorkflowsPanel'
import type { Workflow } from '../api/workflows'

const TABS = [
  { id: 'here', label: 'In this project' },
  { id: 'shared', label: 'Shared' },
] as const
type TabId = (typeof TABS)[number]['id']

export default function WorkflowsPage() {
  const { data: pluginList } = usePlugins()
  const [tab, setTab] = useTabParam<TabId>(TABS, 'here')

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
      <TabNav
        label="Workflows"
        tabs={[...TABS]}
        value={tab}
        onChange={setTab}
      />
      <TabPanel id="here" value={tab}>
        <WorkflowsPanel
          onRun={(wf) => setRunTarget(wf)}
          onView={(wf) => setSummaryTarget(wf)}
        />
      </TabPanel>
      <TabPanel id="shared" value={tab}>
        <LibraryPanel />
      </TabPanel>

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
