import { useContainerPlugins } from '../../hooks/useContainerPlugins'
import { DataTable, type DataTableColumn, Button } from '../ui'
import type { ContainerPluginInfo } from '../../api/containerPlugins'

export function ContainerPluginsPanel() {
  const { data: containerPlugins } = useContainerPlugins()

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
        <span className="font-mono text-xs text-fg-muted">
          {p.files.length}
        </span>
      ),
    },
  ]

  return (
    <div>
      <DataTable
        columns={columns}
        rows={containerPlugins}
        getRowId={(p) => p.name}
        emptyTitle="No container plugins"
        actions={(p) => (
          <Button
            size="sm"
            to={`/plugins/container/${encodeURIComponent(p.name)}/edit`}
            target="_blank"
            rel="opener"
          >
            Edit
          </Button>
        )}
        actionsLabel="Actions"
        actionsWidth="96px"
      />
    </div>
  )
}
