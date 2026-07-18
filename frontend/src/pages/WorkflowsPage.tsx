import { useState, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  useWorkflows,
  useWorkflow,
  useSaveWorkflow,
  useDeleteWorkflow,
} from '../hooks/useWorkflows'
import { PageHeader, Button, LoadingState, ErrorState } from '../components/ui'
import { WorkflowRunModal } from '../components/workflows/WorkflowRunModal'
import type { Workflow } from '../api/workflows'
import { api } from '../api/client'

interface PluginInfo {
  id: string
  description: string
  builtin: boolean
}

function usePlugins() {
  return useQuery<PluginInfo[]>({
    queryKey: ['plugins'],
    queryFn: () => api.get<PluginInfo[]>('/plugins'),
    staleTime: 30_000,
  })
}

function useUploadPlugin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch('/api/plugins/upload', {
        method: 'POST',
        body: form,
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail ?? `HTTP ${res.status}`)
      }
      return res.json()
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['plugins'] }),
  })
}

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
}

function WorkflowEditor({ stem: initialStem, isNew, onClose }: EditorProps) {
  const [stem, setStem] = useState(initialStem)
  const [content, setContent] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const { data: detail, isLoading } = useWorkflow(isNew ? '' : initialStem)
  const save = useSaveWorkflow()

  // Populate content once loaded
  if (!isNew && detail && content === null) {
    setContent(detail.content)
  }
  if (isNew && content === null) {
    setContent(NEW_TEMPLATE)
  }

  // Tab key → 2 spaces
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Tab') {
        e.preventDefault()
        const el = e.currentTarget
        const start = el.selectionStart
        const end = el.selectionEnd
        const next = el.value.slice(0, start) + '  ' + el.value.slice(end)
        setContent(next)
        requestAnimationFrame(() => {
          el.selectionStart = el.selectionEnd = start + 2
        })
      }
    },
    [],
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
              <textarea
                ref={textareaRef}
                value={content ?? ''}
                onChange={(e) => setContent(e.target.value)}
                onKeyDown={handleKeyDown}
                spellCheck={false}
                className="flex-1 min-h-0 font-mono text-xs border border-[#d0d7de] rounded-md p-3 resize-none bg-[#f6f8fa] focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da] leading-relaxed"
                style={{ minHeight: '200px' }}
              />
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
// Main page
// ---------------------------------------------------------------------------

export default function WorkflowsPage() {
  const { data: workflows, isLoading, error } = useWorkflows()
  const { data: pluginList } = usePlugins()
  const uploadPlugin = useUploadPlugin()
  const deleteWf = useDeleteWorkflow()
  const pluginInputRef = useRef<HTMLInputElement>(null)

  const [editor, setEditor] = useState<{ stem: string; isNew: boolean } | null>(
    null,
  )
  const [runTarget, setRunTarget] = useState<Workflow | null>(null)
  const [pluginUploadError, setPluginUploadError] = useState<string | null>(
    null,
  )

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
              </tr>
            </thead>
            <tbody>
              {pluginList.map((p) => (
                <tr
                  key={p.id}
                  className="border-b border-[#d0d7de] hover:bg-[#f6f8fa]"
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
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {pluginList?.length === 0 && (
          <p className="text-sm text-[#656d76]">No plugins loaded yet.</p>
        )}
      </div>

      {/* YAML editor modal */}
      {editor && (
        <WorkflowEditor
          stem={editor.stem}
          isNew={editor.isNew}
          onClose={() => setEditor(null)}
        />
      )}

      {runTarget && (
        <WorkflowRunModal
          workflow={runTarget}
          onClose={() => setRunTarget(null)}
        />
      )}
    </>
  )
}
