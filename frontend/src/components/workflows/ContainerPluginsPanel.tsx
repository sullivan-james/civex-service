import { useState } from 'react'
import { useContainerPlugins } from '../../hooks/useContainerPlugins'
import { DataTable, type DataTableColumn, Button } from '../ui'
import { ContainerPluginEditor } from './ContainerPluginEditor'
import type { ContainerPluginInfo } from '../../api/containerPlugins'

export function ContainerPluginsPanel() {
  const { data: containerPlugins } = useContainerPlugins()
  const [editorTarget, setEditorTarget] = useState<string | null>(null)

  if (!containerPlugins || containerPlugins.length === 0) return null

  const columns: DataTableColumn<ContainerPluginInfo>[] = [
    {
      key: 'name',
      header: 'Name',
      render: (p) => <span className="font-medium text-fg">{p.name}</span>,
    },
    {
      key: 'files',
      header: 'Files',
      align: 'right',
      width: '80px',
      render: (p) => (
        <span className="font-mono text-xs text-fg-muted">{p.files.length}</span>
      ),
    },
  ]

  return (
    <div className="mt-8">
      <div className="mb-3">
        <h2 className="text-base font-semibold text-fg">Container plugins</h2>
        <p className="text-xs text-fg-muted mt-1">
          Tier 2 plugins — Dockerfile + source tree, from{' '}
          _civex/plugins/&lt;name&gt;/
        </p>
      </div>
      <DataTable
        columns={columns}
        rows={containerPlugins}
        getRowId={(p) => p.name}
        emptyTitle="No container plugins"
        actions={(p) => (
          <div className="flex justify-end">
            <Button size="sm" variant="default" onClick={() => setEditorTarget(p.name)}>
              Edit
            </Button>
          </div>
        )}
        actionsLabel="Actions"
        actionsWidth="96px"
      />

      {editorTarget && (
        <ContainerPluginEditor
          name={editorTarget}
          onClose={() => setEditorTarget(null)}
        />
      )}
    </div>
  )
}
