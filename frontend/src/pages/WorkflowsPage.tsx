import { Fragment, useState, useRef, useCallback } from 'react'
import CodeMirror, {
  type EditorView,
  type ViewUpdate,
} from '@uiw/react-codemirror'
import { yaml } from '@codemirror/lang-yaml'
import {
  useWorkflows,
  useWorkflow,
  useSaveWorkflow,
  useDeleteWorkflow,
} from '../hooks/useWorkflows'
import { usePlugins, useUploadPlugin } from '../hooks/usePlugins'
import { PageHeader, Button, LoadingState, ErrorState } from '../components/ui'
import { WorkflowRunModal } from '../components/workflows/WorkflowRunModal'
import { ContainerPluginEditor } from '../components/workflows/ContainerPluginEditor'
import { useContainerPlugins } from '../hooks/useContainerPlugins'
import { PluginEditor } from '../components/plugins/PluginEditor'
import { AutocompleteMenu } from '../components/workflows/YamlAutocomplete'
import {
  getAutocompleteContext,
  getSuggestions,
  type Suggestion,
} from '../utils/workflowAutocomplete'
import type { Workflow } from '../api/workflows'
import type { PluginInfo, PluginIOSpec } from '../api/plugins'

const NEW_TEMPLATE = `name: my-workflow
description: null

triggers:
  record_created:
    schema: MySchema
  # record_updated:
  #   schema: MySchema
  #   fields:
  #     - my_field

steps:
  - id: load_bytes
    plugin: civex.load_file
    config:
      field: my_file_field

  - id: parse_csv
    plugin: civex.load_csv
    config:
      delimiter: ","
    inputs:
      bytes: load_bytes.bytes
`

// ---------------------------------------------------------------------------
// YAML editor modal
// ---------------------------------------------------------------------------

interface EditorProps {
  stem: string
  isNew: boolean
  onClose: () => void
  plugins: PluginInfo[]
}

function WorkflowEditor({
  stem: initialStem,
  isNew,
  onClose,
  plugins,
}: EditorProps) {
  const [stem, setStem] = useState(initialStem)
  const [content, setContent] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  const { data: detail, isLoading } = useWorkflow(isNew ? '' : initialStem)
  const save = useSaveWorkflow()

  // Populate content once loaded
  if (!isNew && detail && content === null) {
    setContent(detail.content)
  }
  if (isNew && content === null) {
    setContent(NEW_TEMPLATE)
  }

  // Autocomplete (CIVEX-122) — plugin ids, config keys, step output refs,
  // driven off the same Story 3 plugin schema the contract panel below reads.
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [activeIndex, setActiveIndex] = useState(0)
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 })
  const acContextRef = useRef<{
    replaceFrom: number
    replaceTo: number
  } | null>(null)
  const viewRef = useRef<EditorView | null>(null)
  const editorWrapRef = useRef<HTMLDivElement>(null)
  // Suppresses the onUpdate-driven refresh for the dispatch applySuggestion
  // itself issues, so accepting a suggestion doesn't immediately reopen the menu.
  const applyingSuggestionRef = useRef(false)

  const refreshSuggestions = useCallback(
    (text: string, cursor: number) => {
      const ctx = getAutocompleteContext(text, cursor)
      const matches = ctx ? getSuggestions(ctx, plugins, text) : []
      if (!ctx || matches.length === 0) {
        acContextRef.current = null
        setSuggestions([])
        return
      }
      acContextRef.current = ctx
      setSuggestions(matches)
      setActiveIndex(0)
      const view = viewRef.current
      const wrap = editorWrapRef.current
      const coords = view?.coordsAtPos(cursor)
      if (coords && wrap) {
        const wrapRect = wrap.getBoundingClientRect()
        setMenuPos({
          top: coords.bottom - wrapRect.top,
          left: coords.left - wrapRect.left,
        })
      }
    },
    [plugins],
  )

  const applySuggestion = useCallback(
    (index: number) => {
      const ctx = acContextRef.current
      const chosen = suggestions[index]
      const view = viewRef.current
      if (!ctx || !chosen || !view) return
      const newCursor = ctx.replaceFrom + chosen.insertText.length
      applyingSuggestionRef.current = true
      view.dispatch({
        changes: {
          from: ctx.replaceFrom,
          to: ctx.replaceTo,
          insert: chosen.insertText,
        },
        selection: { anchor: newCursor },
      })
      acContextRef.current = null
      setSuggestions([])
      view.focus()
    },
    [suggestions],
  )

  const handleUpdate = useCallback(
    (update: ViewUpdate) => {
      viewRef.current = update.view
      if (applyingSuggestionRef.current) {
        applyingSuggestionRef.current = false
        return
      }
      if (!update.docChanged && !update.selectionSet) return
      refreshSuggestions(
        update.state.doc.toString(),
        update.state.selection.main.head,
      )
    },
    [refreshSuggestions],
  )

  // Intercepted in the capture phase so the keys never reach CodeMirror's
  // own keymap (e.g. Tab-to-indent) while the suggestion menu is open.
  const handleEditorKeyDownCapture = useCallback(
    (e: React.KeyboardEvent) => {
      if (suggestions.length === 0) return
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        e.stopPropagation()
        setActiveIndex((i) => (i + 1) % suggestions.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        e.stopPropagation()
        setActiveIndex((i) => (i - 1 + suggestions.length) % suggestions.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        e.stopPropagation()
        applySuggestion(activeIndex)
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        setSuggestions([])
        return
      }
    },
    [suggestions, activeIndex, applySuggestion],
  )

  async function handleSave() {
    if (!stem.trim() || content === null) return
    setSaveError(null)
    try {
      await save.mutateAsync({ stem: stem.trim(), content })
      onClose()
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed')
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-3xl flex flex-col"
        style={{ height: '90vh' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#d0d7de]">
          <h2 className="text-base font-semibold text-[#1f2328]">
            {isNew ? 'New workflow' : `Edit — ${initialStem}.yaml`}
          </h2>
          <button
            onClick={onClose}
            className="text-[#656d76] hover:text-[#1f2328] text-xl leading-none"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="flex flex-col gap-3 p-5 flex-1 min-h-0">
          {isNew && (
            <label className="block">
              <span className="text-xs font-medium text-[#1f2328]">
                Filename stem
              </span>
              <div className="flex items-center gap-1 mt-1">
                <input
                  type="text"
                  value={stem}
                  onChange={(e) =>
                    setStem(e.target.value.replace(/[^a-zA-Z0-9_-]/g, ''))
                  }
                  placeholder="my-workflow"
                  className="border border-[#d0d7de] rounded-md px-3 py-1.5 text-sm w-56 focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
                />
                <span className="text-sm text-[#656d76]">.yaml</span>
              </div>
              <p className="text-xs text-[#656d76] mt-1">
                Letters, numbers, hyphens and underscores only.
              </p>
            </label>
          )}

          {isLoading ? (
            <div className="flex-1 flex items-center justify-center text-sm text-[#656d76]">
              Loading…
            </div>
          ) : (
            <div className="flex-1 flex flex-col min-h-0">
              <span className="text-xs font-medium text-[#1f2328] mb-1">
                YAML
              </span>
              <div
                ref={editorWrapRef}
                onKeyDownCapture={handleEditorKeyDownCapture}
                className="relative flex-1 min-h-0 overflow-auto border border-[#d0d7de] rounded-md bg-[#f6f8fa] focus-within:border-[#0969da] focus-within:ring-1 focus-within:ring-[#0969da]"
                style={{ minHeight: '200px' }}
              >
                <CodeMirror
                  value={content ?? ''}
                  onChange={(value) => setContent(value)}
                  onUpdate={handleUpdate}
                  onCreateEditor={(view) => {
                    viewRef.current = view
                  }}
                  onBlur={() => setSuggestions([])}
                  extensions={[yaml()]}
                  basicSetup={{ tabSize: 2 }}
                  indentWithTab
                  height="100%"
                  className="h-full text-xs"
                  style={{ height: '100%' }}
                />
                <AutocompleteMenu
                  suggestions={suggestions}
                  activeIndex={activeIndex}
                  position={menuPos}
                  onSelect={applySuggestion}
                />
              </div>
            </div>
          )}

          {saveError && (
            <pre className="text-xs text-red-600 bg-red-50 border border-red-200 rounded p-2 whitespace-pre-wrap">
              {saveError}
            </pre>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-[#d0d7de]">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleSave}
            disabled={save.isPending || !stem.trim()}
          >
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Plugin contract detail (CIVEX-144) — one declared contract (config keys,
// inputs, outputs, capabilities), same shape for every tier, read straight
// off GET /plugins rather than a second endpoint.
// ---------------------------------------------------------------------------

function IOSpecList({ specs }: { specs: PluginIOSpec[] | null }) {
  if (specs === null) {
    return <p className="text-xs text-[#656d76] italic">not declared</p>
  }
  if (specs.length === 0) {
    return <p className="text-xs text-[#656d76]">none</p>
  }
  return (
    <ul className="text-xs space-y-0.5">
      {specs.map((s) => (
        <li key={s.name} className="font-mono">
          <span className="text-[#1f2328]">{s.name}</span>
          <span className="text-[#656d76]"> : {s.type}</span>
          {!s.required && <span className="text-[#656d76]"> (optional)</span>}
          {s.description && (
            <span className="text-[#656d76] font-sans"> — {s.description}</span>
          )}
        </li>
      ))}
    </ul>
  )
}

function PluginContractDetail({ plugin }: { plugin: PluginInfo }) {
  const configProps = Object.entries(plugin.config_schema.properties ?? {})
  const required = new Set(plugin.config_schema.required ?? [])

  return (
    <div className="grid grid-cols-3 gap-4">
      <div>
        <h4 className="text-xs font-semibold text-[#1f2328] mb-1">Inputs</h4>
        <IOSpecList specs={plugin.inputs} />
      </div>
      <div>
        <h4 className="text-xs font-semibold text-[#1f2328] mb-1">Outputs</h4>
        <IOSpecList specs={plugin.outputs} />
      </div>
      <div>
        <h4 className="text-xs font-semibold text-[#1f2328] mb-1">Config</h4>
        {configProps.length === 0 ? (
          <p className="text-xs text-[#656d76]">none</p>
        ) : (
          <ul className="text-xs space-y-0.5">
            {configProps.map(([key, prop]) => (
              <li key={key} className="font-mono">
                <span className="text-[#1f2328]">{key}</span>
                <span className="text-[#656d76]"> : {prop.type ?? 'any'}</span>
                {!required.has(key) && (
                  <span className="text-[#656d76]"> (optional)</span>
                )}
              </li>
            ))}
          </ul>
        )}
        {plugin.capabilities.length > 0 && (
          <>
            <h4 className="text-xs font-semibold text-[#1f2328] mt-2 mb-1">
              Capabilities
            </h4>
            <p className="text-xs font-mono text-[#656d76]">
              {plugin.capabilities.join(', ')}
            </p>
          </>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function WorkflowsPage() {
  const { data: workflows, isLoading, error } = useWorkflows()
  const { data: pluginList } = usePlugins()
  const { data: containerPlugins } = useContainerPlugins()
  const uploadPlugin = useUploadPlugin()
  const deleteWf = useDeleteWorkflow()
  const pluginInputRef = useRef<HTMLInputElement>(null)
  const [expandedPlugin, setExpandedPlugin] = useState<string | null>(null)

  const [editor, setEditor] = useState<{ stem: string; isNew: boolean } | null>(
    null,
  )
  const [runTarget, setRunTarget] = useState<Workflow | null>(null)
  const [pluginUploadError, setPluginUploadError] = useState<string | null>(
    null,
  )
  const [containerEditorTarget, setContainerEditorTarget] = useState<
    string | null
  >(null)
  const [pluginEditor, setPluginEditor] = useState<{
    filename: string
    isNew: boolean
  } | null>(null)

  async function handlePluginFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    setPluginUploadError(null)
    try {
      await uploadPlugin.mutateAsync(file)
    } catch (err) {
      setPluginUploadError(err instanceof Error ? err.message : String(err))
    }
  }

  function openNew() {
    setEditor({ stem: 'new-workflow', isNew: true })
  }

  function openEdit(wf: Workflow) {
    setEditor({ stem: wf.stem, isNew: false })
  }

  function openNewPlugin() {
    setPluginEditor({ filename: '', isNew: true })
  }

  function openEditPlugin(filename: string) {
    setPluginEditor({ filename, isNew: false })
  }

  async function handleDelete(wf: Workflow) {
    if (!confirm(`Delete workflow '${wf.name}'? This cannot be undone.`)) return
    deleteWf.mutate(wf.stem)
  }

  function openRun(wf: Workflow) {
    setRunTarget(wf)
  }

  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message={error.message} />

  return (
    <>
      <PageHeader
        title="Workflows"
        description="YAML workflow definitions in .civex/workflows/"
        action={
          <Button variant="primary" size="sm" onClick={openNew}>
            + New workflow
          </Button>
        }
      />

      {!workflows?.length ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <svg
            width="40"
            height="40"
            viewBox="0 0 16 16"
            fill="none"
            className="mb-4 text-[#d0d7de]"
            aria-hidden
          >
            <circle
              cx="3"
              cy="3"
              r="2"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <circle
              cx="13"
              cy="3"
              r="2"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <circle
              cx="8"
              cy="13"
              r="2"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <path
              d="M5 3h6M10.5 4.5l-2 7M5.5 4.5l2 7"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
          <h2 className="text-lg font-semibold text-[#1f2328] mb-2">
            No workflows yet
          </h2>
          <p className="text-sm text-[#656d76] mb-6 max-w-sm">
            Workflows automate data processing — they run when records are
            created or updated. Create a .yaml file in .civex/workflows/ to get
            started.
          </p>
        </div>
      ) : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-[#d0d7de]">
              <th className="text-left py-2 px-3 font-medium text-[#1f2328]">
                Name
              </th>
              <th className="text-left py-2 px-3 font-medium text-[#1f2328]">
                Description
              </th>
              <th className="text-left py-2 px-3 font-medium text-[#1f2328]">
                Steps
              </th>
              <th className="text-left py-2 px-3 font-medium text-[#1f2328]">
                File
              </th>
              <th className="py-2 px-3 text-right" />
            </tr>
          </thead>
          <tbody>
            {workflows.map((wf) => (
              <tr
                key={wf.stem}
                className="border-b border-[#d0d7de] hover:bg-[#f6f8fa]"
              >
                <td className="py-2 px-3 font-medium text-[#1f2328]">
                  {wf.name}
                </td>
                <td className="py-2 px-3 text-[#656d76]">
                  {wf.description ?? '—'}
                </td>
                <td className="py-2 px-3 text-[#656d76]">{wf.steps}</td>
                <td className="py-2 px-3 font-mono text-xs text-[#656d76]">
                  {wf.filename}
                </td>
                <td className="py-2 px-3">
                  <div className="flex justify-end gap-2">
                    <Button size="sm" onClick={() => openRun(wf)}>
                      Run
                    </Button>
                    <Button
                      size="sm"
                      variant="default"
                      onClick={() => openEdit(wf)}
                    >
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={() => handleDelete(wf)}
                    >
                      Delete
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Plugins panel */}
      <input
        ref={pluginInputRef}
        type="file"
        accept=".py"
        className="hidden"
        onChange={handlePluginFile}
      />
      <div className="mt-10">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-base font-semibold text-[#1f2328]">Plugins</h2>
            <p className="text-xs text-[#656d76] mt-0.5">
              Step implementations available to workflows
            </p>
          </div>
          <div className="flex items-center gap-2">
            {pluginUploadError && (
              <span className="text-xs text-[#d1242f]">
                {pluginUploadError}
              </span>
            )}
            <Button
              size="sm"
              variant="default"
              onClick={() => pluginInputRef.current?.click()}
              disabled={uploadPlugin.isPending}
            >
              {uploadPlugin.isPending ? 'Uploading…' : 'Upload plugin'}
            </Button>
            <Button size="sm" variant="primary" onClick={openNewPlugin}>
              + New plugin
            </Button>
          </div>
        </div>
        {pluginList && pluginList.length > 0 && (
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-[#d0d7de]">
                <th className="text-left py-2 px-3 font-medium text-[#1f2328]">
                  Plugin ID
                </th>
                <th className="text-left py-2 px-3 font-medium text-[#1f2328]">
                  Description
                </th>
                <th className="text-left py-2 px-3 font-medium text-[#1f2328]">
                  Source
                </th>
                <th className="py-2 px-3" />
                <th className="py-2 px-3 text-right" />
              </tr>
            </thead>
            <tbody>
              {pluginList.map((p) => {
                const isExpanded = expandedPlugin === p.id
                return (
                  <Fragment key={p.id}>
                    <tr
                      onClick={() =>
                        setExpandedPlugin(isExpanded ? null : p.id)
                      }
                      className="border-b border-[#d0d7de] hover:bg-[#f6f8fa] cursor-pointer"
                    >
                      <td className="py-2 px-3 font-mono text-xs text-[#1f2328]">
                        {p.id}
                      </td>
                      <td className="py-2 px-3 text-[#656d76]">
                        {p.description || '—'}
                      </td>
                      <td className="py-2 px-3">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                            p.builtin
                              ? 'bg-[#ddf4ff] text-[#0969da]'
                              : 'bg-[#dafbe1] text-[#1a7f37]'
                          }`}
                        >
                          {p.builtin ? 'built-in' : 'user'}
                        </span>
                      </td>
                      <td className="py-2 px-3 text-[#656d76] text-xs">
                        {isExpanded ? '▲' : '▼'}
                      </td>
                      <td className="py-2 px-3 text-right">
                        {p.filename && (
                          <Button
                            size="sm"
                            variant="default"
                            onClick={(e) => {
                              e.stopPropagation()
                              openEditPlugin(p.filename!)
                            }}
                          >
                            Edit
                          </Button>
                        )}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="border-b border-[#d0d7de]">
                        <td colSpan={5} className="bg-[#f6f8fa] px-3 py-3">
                          <PluginContractDetail plugin={p} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        )}
        {pluginList?.length === 0 && (
          <p className="text-sm text-[#656d76]">No plugins loaded yet.</p>
        )}
      </div>

      {/* Container (Tier 2) plugins panel */}
      {containerPlugins && containerPlugins.length > 0 && (
        <div className="mt-10">
          <div className="mb-3">
            <h2 className="text-base font-semibold text-[#1f2328]">
              Container plugins
            </h2>
            <p className="text-xs text-[#656d76] mt-0.5">
              Tier 2 plugins — Dockerfile + source tree, from{' '}
              _civex/plugins/&lt;name&gt;/
            </p>
          </div>
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-[#d0d7de]">
                <th className="text-left py-2 px-3 font-medium text-[#1f2328]">
                  Name
                </th>
                <th className="text-left py-2 px-3 font-medium text-[#1f2328]">
                  Files
                </th>
                <th className="py-2 px-3 text-right" />
              </tr>
            </thead>
            <tbody>
              {containerPlugins.map((p) => (
                <tr
                  key={p.name}
                  className="border-b border-[#d0d7de] hover:bg-[#f6f8fa]"
                >
                  <td className="py-2 px-3 font-medium text-[#1f2328]">
                    {p.name}
                  </td>
                  <td className="py-2 px-3 font-mono text-xs text-[#656d76]">
                    {p.files.length}
                  </td>
                  <td className="py-2 px-3">
                    <div className="flex justify-end">
                      <Button
                        size="sm"
                        variant="default"
                        onClick={() => setContainerEditorTarget(p.name)}
                      >
                        Edit
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* YAML editor modal */}
      {editor && (
        <WorkflowEditor
          stem={editor.stem}
          isNew={editor.isNew}
          onClose={() => setEditor(null)}
          plugins={pluginList ?? []}
        />
      )}

      {pluginEditor && (
        <PluginEditor
          filename={pluginEditor.filename}
          isNew={pluginEditor.isNew}
          onClose={() => setPluginEditor(null)}
        />
      )}

      {runTarget && (
        <WorkflowRunModal
          workflow={runTarget}
          onClose={() => setRunTarget(null)}
        />
      )}

      {containerEditorTarget && (
        <ContainerPluginEditor
          name={containerEditorTarget}
          onClose={() => setContainerEditorTarget(null)}
        />
      )}
    </>
  )
}
