import { useRef, useState } from 'react'
import {
  useDeletePlugin,
  usePlugins,
  usePluginLoadErrors,
  useUploadPlugin,
} from '../../hooks/usePlugins'
import { DataTable, type DataTableColumn, Badge, Button, ConfirmDialog } from '../ui'
import { ChevronUp, ChevronDown } from '../ui/icons'
import { PluginEditor } from '../plugins/PluginEditor'
import type { PluginInfo, PluginIOSpec, PluginLoadError } from '../../api/plugins'

function IOSpecList({ specs }: { specs: PluginIOSpec[] | null }) {
  if (specs === null) {
    return <p className="text-xs text-fg-muted italic">not declared</p>
  }
  if (specs.length === 0) {
    return <p className="text-xs text-fg-muted">none</p>
  }
  return (
    <ul className="text-xs space-y-1">
      {specs.map((s) => (
        <li key={s.name} className="font-mono">
          <span className="text-fg">{s.name}</span>
          <span className="text-fg-muted"> : {s.type}</span>
          {!s.required && <span className="text-fg-muted"> (optional)</span>}
          {s.description && (
            <span className="text-fg-muted font-sans"> — {s.description}</span>
          )}
        </li>
      ))}
    </ul>
  )
}

// ---------------------------------------------------------------------------
// Plugin contract detail (CIVEX-144) — one declared contract (config keys,
// inputs, outputs, capabilities), same shape for every tier, read straight
// off GET /plugins rather than a second endpoint.
// ---------------------------------------------------------------------------

function PluginContractDetail({ plugin }: { plugin: PluginInfo }) {
  const configProps = Object.entries(plugin.config_schema.properties ?? {})
  const required = new Set(plugin.config_schema.required ?? [])

  return (
    <div className="grid grid-cols-3 gap-4">
      <div>
        <h4 className="text-xs font-semibold text-fg mb-1">Inputs</h4>
        <IOSpecList specs={plugin.inputs} />
      </div>
      <div>
        <h4 className="text-xs font-semibold text-fg mb-1">Outputs</h4>
        <IOSpecList specs={plugin.outputs} />
      </div>
      <div>
        <h4 className="text-xs font-semibold text-fg mb-1">Config</h4>
        {configProps.length === 0 ? (
          <p className="text-xs text-fg-muted">none</p>
        ) : (
          <ul className="text-xs space-y-1">
            {configProps.map(([key, prop]) => (
              <li key={key} className="font-mono">
                <span className="text-fg">{key}</span>
                <span className="text-fg-muted"> : {prop.type ?? 'any'}</span>
                {!required.has(key) && (
                  <span className="text-fg-muted"> (optional)</span>
                )}
                {prop.description && (
                  <span className="text-fg-muted font-sans">
                    {' '}
                    — {prop.description}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        {plugin.capabilities.length > 0 && (
          <>
            <h4 className="text-xs font-semibold text-fg mt-2 mb-1">
              Capabilities
            </h4>
            <p className="text-xs font-mono text-fg-muted">
              {plugin.capabilities.join(', ')}
            </p>
          </>
        )}
      </div>
    </div>
  )
}

interface DeleteTarget {
  id: string
  filename: string
}

export function PluginsPanel() {
  const { data: pluginList } = usePlugins()
  const { data: pluginLoadErrors } = usePluginLoadErrors()
  const uploadPlugin = useUploadPlugin()
  const deletePlugin = useDeletePlugin()
  const pluginInputRef = useRef<HTMLInputElement>(null)

  const [expandedPlugin, setExpandedPlugin] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null)
  const [deleteWarning, setDeleteWarning] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [pluginEditor, setPluginEditor] = useState<{
    filename: string
    isNew: boolean
  } | null>(null)

  async function handlePluginFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    setUploadError(null)
    try {
      await uploadPlugin.mutateAsync(file)
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err))
    }
  }

  function openDelete(id: string, filename: string) {
    setDeleteError(null)
    setDeleteWarning(null)
    setDeleteTarget({ id, filename })
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    try {
      await deletePlugin.mutateAsync({
        filename: deleteTarget.filename,
        force: deleteWarning !== null,
      })
      setDeleteTarget(null)
      setDeleteWarning(null)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Delete failed'
      if (deleteWarning === null) {
        setDeleteWarning(message)
      } else {
        setDeleteError(message)
        setDeleteTarget(null)
        setDeleteWarning(null)
      }
    }
  }

  const pluginColumns: DataTableColumn<PluginInfo>[] = [
    {
      key: 'id',
      header: 'Plugin ID',
      render: (p) => <span className="font-mono text-xs text-fg">{p.id}</span>,
    },
    {
      key: 'description',
      header: 'Description',
      render: (p) => (
        <span className="text-fg-muted">{p.description || '—'}</span>
      ),
    },
    {
      key: 'source',
      header: 'Source',
      render: (p) => (
        <Badge variant={p.builtin ? 'accent' : 'success'}>
          {p.builtin ? 'built-in' : 'user'}
        </Badge>
      ),
    },
    {
      key: 'expand',
      header: '',
      width: '40px',
      render: (p) => (
        <Button
          size="sm"
          variant="default"
          title={expandedPlugin === p.id ? 'Hide contract' : 'Show contract'}
          onClick={() =>
            setExpandedPlugin(expandedPlugin === p.id ? null : p.id)
          }
        >
          {expandedPlugin === p.id ? (
            <ChevronUp size={12} />
          ) : (
            <ChevronDown size={12} />
          )}
        </Button>
      ),
    },
  ]

  const errorColumns: DataTableColumn<PluginLoadError>[] = [
    {
      key: 'filename',
      header: 'Failed to load',
      render: (e) => <span className="font-mono text-xs text-fg">{e.filename}</span>,
    },
    {
      key: 'error',
      header: 'Error',
      render: (e) => (
        <span className="text-danger text-xs whitespace-pre-wrap">
          {e.error}
        </span>
      ),
    },
  ]

  const expandedPluginInfo = pluginList?.find((p) => p.id === expandedPlugin)

  return (
    <div className="mt-8">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-base font-semibold text-fg">Plugins</h2>
          <p className="text-xs text-fg-muted mt-1">
            Step implementations available to workflows
          </p>
        </div>
        <div className="flex items-center gap-2">
          {uploadError && <span className="text-xs text-danger">{uploadError}</span>}
          <Button
            size="sm"
            variant="default"
            onClick={() => pluginInputRef.current?.click()}
            disabled={uploadPlugin.isPending}
          >
            {uploadPlugin.isPending ? 'Uploading…' : 'Upload plugin'}
          </Button>
          <Button
            size="sm"
            variant="primary"
            onClick={() => setPluginEditor({ filename: '', isNew: true })}
          >
            + New plugin
          </Button>
        </div>
      </div>
      <input
        ref={pluginInputRef}
        type="file"
        accept=".py"
        className="hidden"
        onChange={handlePluginFile}
      />
      {deleteError && <p className="text-xs text-danger mb-2">{deleteError}</p>}

      {pluginList && pluginList.length > 0 && (
        <DataTable
          columns={pluginColumns}
          rows={pluginList}
          getRowId={(p) => p.id}
          emptyTitle="No plugins loaded yet"
          actions={(p) =>
            p.filename ? (
              <div className="flex justify-end gap-2">
                <Button
                  size="sm"
                  variant="default"
                  onClick={() => setPluginEditor({ filename: p.filename!, isNew: false })}
                >
                  Edit
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={deletePlugin.isPending}
                  onClick={() => openDelete(p.id, p.filename!)}
                >
                  Delete
                </Button>
              </div>
            ) : null
          }
          actionsLabel="Actions"
          actionsWidth="160px"
        />
      )}
      {pluginList?.length === 0 && (
        <p className="text-sm text-fg-muted">No plugins loaded yet.</p>
      )}

      {expandedPluginInfo && (
        <div className="mt-3 border border-border rounded-md bg-canvas-subtle px-3 py-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-fg font-mono">
              {expandedPluginInfo.id}
            </span>
            <Button size="sm" variant="default" onClick={() => setExpandedPlugin(null)}>
              Close
            </Button>
          </div>
          <PluginContractDetail plugin={expandedPluginInfo} />
        </div>
      )}

      {pluginLoadErrors && pluginLoadErrors.length > 0 && (
        <div className="mt-3">
          <DataTable
            columns={errorColumns}
            rows={pluginLoadErrors}
            getRowId={(e) => e.filename}
            emptyTitle="No errors"
            actions={(e) => (
              <div className="flex justify-end gap-2">
                <Button
                  size="sm"
                  variant="default"
                  onClick={() => setPluginEditor({ filename: e.filename, isNew: false })}
                >
                  Edit
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={deletePlugin.isPending}
                  onClick={() => openDelete(e.filename, e.filename)}
                >
                  Delete
                </Button>
              </div>
            )}
            actionsLabel="Actions"
            actionsWidth="160px"
          />
        </div>
      )}

      {pluginEditor && (
        <PluginEditor
          filename={pluginEditor.filename}
          isNew={pluginEditor.isNew}
          onClose={() => setPluginEditor(null)}
        />
      )}

      {deleteTarget && (
        <ConfirmDialog
          title="Delete plugin"
          body={`Delete plugin '${deleteTarget.id}'? This cannot be undone.`}
          confirmLabel={deleteWarning ? 'Delete anyway' : 'Delete'}
          variant="danger"
          warning={deleteWarning}
          isPending={deletePlugin.isPending}
          onConfirm={confirmDelete}
          onClose={() => {
            setDeleteTarget(null)
            setDeleteWarning(null)
          }}
        />
      )}
    </div>
  )
}
