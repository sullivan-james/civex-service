import { Page, TabNav, TabPanel, useTabParam } from '../components/ui'
import { PluginsPanel } from '../components/workflows/PluginsPanel'
import { ContainerPluginsPanel } from '../components/workflows/ContainerPluginsPanel'

const TABS = [
  { id: 'python' as const, label: 'Python' },
  {
    id: 'container' as const,
    label: 'Container',
  },
]

export default function PluginsPage() {
  const [tab, setTab] = useTabParam(TABS, 'python')
  return (
    <Page
      title="Plugins"
      tabs={
        <TabNav label="Plugin kind" tabs={TABS} value={tab} onChange={setTab} />
      }
    >
      <TabPanel id="python" value={tab}>
        <PluginsPanel />
      </TabPanel>
      <TabPanel id="container" value={tab}>
        <ContainerPluginsPanel />
      </TabPanel>
    </Page>
  )
}
