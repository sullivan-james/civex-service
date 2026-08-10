import { Page } from '../components/ui'
import { PluginsPanel } from '../components/workflows/PluginsPanel'
import { ContainerPluginsPanel } from '../components/workflows/ContainerPluginsPanel'

export default function PluginsPage() {
  return (
    <Page
      title="Plugins"
      description="Step implementations available to workflows — Python (Tier 1) and container (Tier 2)"
    >
      <PluginsPanel />
      <ContainerPluginsPanel />
    </Page>
  )
}
