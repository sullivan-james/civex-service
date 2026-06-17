import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useRunWorkflow, useRunWorkflowWithFiles } from '../../hooks/useWorkflows'
import { Button } from '../ui'
import type { Workflow } from '../../api/workflows'

interface Props {
  workflow: Workflow
  /** Pre-fill the record ID field and lock it. */
  recordId?: string
  onClose: () => void
}

export function WorkflowRunModal({ workflow, recordId: prefilled, onClose }: Props) {
  const navigate = useNavigate()
  const [recordId, setRecordId] = useState(prefilled ?? '')
  const [fileInputs, setFileInputs] = useState<Record<string, File[]>>({})
  const [error, setError] = useState<string | null>(null)
  const fileRefs = useRef<Record<string, HTMLInputElement | null>>({})

  const runPlain = useRunWorkflow()
  const runFiles = useRunWorkflowWithFiles()

  const filesInputs = Object.entries(workflow.inputs ?? {}).filter(([, v]) => v.type === 'files')
  const hasFileInputs = filesInputs.length > 0
  const isPending = runPlain.isPending || runFiles.isPending

  function handleFileChange(inputName: string, files: FileList | null) {
    setFileInputs(prev => ({ ...prev, [inputName]: files ? Array.from(files) : [] }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      if (hasFileInputs) {
        await runFiles.mutateAsync({ name: workflow.name, recordId: recordId.trim(), fileInputs })
      } else {
        await runPlain.mutateAsync({ name: workflow.name, recordId: recordId.trim() })
      }
      onClose()
      if (!prefilled) navigate('/jobs')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to enqueue workflow')
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="bg-white rounded-lg shadow-lg w-full max-w-md flex flex-col" style={{ maxHeight: '90vh' }}>
        {/* Header */}
        <div className="px-6 pt-6 pb-4 shrink-0">
          <h2 className="text-base font-semibold text-[#1f2328] mb-1">
            Run <span className="font-mono">{workflow.name}</span>
          </h2>
          {workflow.description && (
            <p className="text-xs text-[#656d76]">{workflow.description}</p>
          )}
        </div>

        {/* Scrollable body */}
        <div className="overflow-y-auto px-6 flex-1 min-h-0">
          <form id="wf-run-form" onSubmit={handleSubmit} className="space-y-4 pb-4">
            <label className="block">
              <span className="text-sm font-medium text-[#1f2328]">Record ID</span>
              {workflow.record_schema && (
                <span className="ml-1.5 text-xs text-[#656d76]">({workflow.record_schema})</span>
              )}
              <input
                autoFocus={!prefilled}
                type="text"
                value={recordId}
                onChange={e => setRecordId(e.target.value)}
                placeholder="Short ID or full UUID"
                readOnly={!!prefilled}
                required
                className={`mt-1 w-full border border-[#d0d7de] rounded-md px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da] ${prefilled ? 'bg-[#f6f8fa] text-[#656d76]' : ''}`}
              />
            </label>

            {filesInputs.map(([inputName, decl]) => {
              const chosen = fileInputs[inputName] ?? []
              return (
                <div key={inputName}>
                  <label className="block text-sm font-medium text-[#1f2328] mb-1">
                    {decl.label ?? inputName}
                  </label>
                  {decl.description && (
                    <p className="text-xs text-[#656d76] mb-2">{decl.description}</p>
                  )}
                  <div
                    className="border-2 border-dashed border-[#d0d7de] rounded-md px-4 py-5 text-center cursor-pointer hover:border-[#0969da] hover:bg-[#f6f8fa] transition-colors"
                    onClick={() => fileRefs.current[inputName]?.click()}
                    onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy' }}
                    onDrop={e => { e.preventDefault(); handleFileChange(inputName, e.dataTransfer.files) }}
                  >
                    <input
                      ref={el => { fileRefs.current[inputName] = el }}
                      type="file"
                      multiple
                      className="hidden"
                      onChange={e => handleFileChange(inputName, e.target.files)}
                    />
                    {chosen.length === 0 ? (
                      <p className="text-sm text-[#656d76]">
                        Drop files here or <span className="text-[#0969da]">browse</span>
                      </p>
                    ) : (
                      <div className="text-left">
                        <div className="max-h-32 overflow-y-auto space-y-0.5 mb-1">
                          {chosen.map((f, i) => (
                            <p key={i} className="text-xs font-mono text-[#1f2328] truncate">{f.name}</p>
                          ))}
                        </div>
                        <p className="text-xs text-[#656d76]">
                          {chosen.length} file{chosen.length !== 1 ? 's' : ''} selected · click or drop to replace
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}

            {error && <p className="text-sm text-[#d1242f]">{error}</p>}
          </form>
        </div>

        {/* Sticky footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-[#d0d7de] shrink-0">
          <Button variant="default" onClick={onClose} type="button">Cancel</Button>
          <Button variant="primary" type="submit" form="wf-run-form" disabled={isPending}>
            {isPending ? 'Queuing…' : 'Run'}
          </Button>
        </div>
      </div>
    </div>
  )
}
