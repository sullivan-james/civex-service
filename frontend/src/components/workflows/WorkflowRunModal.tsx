import { useState, useRef } from 'react'
import { useNavigate } from 'react-router'
import {
  useRunWorkflow,
  useRunWorkflowWithFiles,
} from '../../hooks/useWorkflows'
import { Button, Input } from '../ui'
import type { Workflow } from '../../api/workflows'

interface Props {
  workflow: Workflow
  /** Pre-fill the record ID field and lock it. */
  recordId?: string
  onClose: () => void
}

export function WorkflowRunModal({
  workflow,
  recordId: prefilled,
  onClose,
}: Props) {
  const navigate = useNavigate()
  const [recordId, setRecordId] = useState(prefilled ?? '')
  const [fileInputs, setFileInputs] = useState<Record<string, File[]>>({})
  const [error, setError] = useState<string | null>(null)
  const fileRefs = useRef<Record<string, HTMLInputElement | null>>({})

  const runPlain = useRunWorkflow()
  const runFiles = useRunWorkflowWithFiles()

  const filesInputs = Object.entries(workflow.inputs ?? {}).filter(
    ([, v]) => v.type === 'files',
  )
  const hasFileInputs = filesInputs.length > 0
  const isPending = runPlain.isPending || runFiles.isPending

  function handleFileChange(inputName: string, files: FileList | null) {
    setFileInputs((prev) => ({
      ...prev,
      [inputName]: files ? Array.from(files) : [],
    }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      if (hasFileInputs) {
        await runFiles.mutateAsync({
          name: workflow.name,
          recordId: recordId.trim(),
          fileInputs,
        })
      } else {
        await runPlain.mutateAsync({
          name: workflow.name,
          recordId: recordId.trim(),
        })
      }
      onClose()
      if (!prefilled) navigate('/jobs')
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to enqueue workflow',
      )
    }
  }

  return (
    <div
      className="fixed inset-0 bg-overlay-scrim flex items-center justify-center z-50 p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="bg-canvas rounded-lg shadow-lg w-full max-w-md flex flex-col"
        style={{ maxHeight: '90vh' }}
      >
        {/* Header */}
        <div className="px-6 pt-6 pb-4 shrink-0">
          <h2 className="text-base font-semibold text-fg mb-1">
            Run <span className="font-mono">{workflow.name}</span>
          </h2>
          {workflow.description && (
            <p className="text-xs text-fg-muted">{workflow.description}</p>
          )}
        </div>

        {/* Scrollable body */}
        <div className="overflow-y-auto px-6 flex-1 min-h-0">
          <form
            id="wf-run-form"
            onSubmit={handleSubmit}
            className="space-y-4 pb-4"
          >
            <label className="block">
              <span className="text-sm font-medium text-fg">Record ID</span>
              {workflow.record_schema && (
                <span className="ml-1.5 text-xs text-fg-muted">
                  ({workflow.record_schema})
                </span>
              )}
              <Input
                autoFocus={!prefilled}
                type="text"
                value={recordId}
                onChange={(e) => setRecordId(e.target.value)}
                placeholder="Short ID or full UUID"
                readOnly={!!prefilled}
                required
                className={`mt-1 w-full font-mono ${prefilled ? 'bg-canvas-subtle text-fg-muted' : ''}`}
              />
            </label>

            {filesInputs.map(([inputName, decl]) => {
              const chosen = fileInputs[inputName] ?? []
              return (
                <div key={inputName}>
                  <label className="block text-sm font-medium text-fg mb-1">
                    {decl.label ?? inputName}
                  </label>
                  {decl.description && (
                    <p className="text-xs text-fg-muted mb-2">
                      {decl.description}
                    </p>
                  )}
                  <div
                    className="border-2 border-dashed border-border rounded-md px-4 py-5 text-center cursor-pointer hover:border-accent hover:bg-canvas-subtle transition-colors"
                    onClick={() => fileRefs.current[inputName]?.click()}
                    onDragOver={(e) => {
                      e.preventDefault()
                      e.dataTransfer.dropEffect = 'copy'
                    }}
                    onDrop={(e) => {
                      e.preventDefault()
                      handleFileChange(inputName, e.dataTransfer.files)
                    }}
                  >
                    <input
                      ref={(el) => {
                        fileRefs.current[inputName] = el
                      }}
                      type="file"
                      multiple
                      className="hidden"
                      onChange={(e) =>
                        handleFileChange(inputName, e.target.files)
                      }
                    />
                    {chosen.length === 0 ? (
                      <p className="text-sm text-fg-muted">
                        Drop files here or{' '}
                        <span className="text-accent">browse</span>
                      </p>
                    ) : (
                      <div className="text-left">
                        <div className="max-h-32 overflow-y-auto space-y-0.5 mb-1">
                          {chosen.map((f, i) => (
                            <p
                              key={i}
                              className="text-xs font-mono text-fg truncate"
                            >
                              {f.name}
                            </p>
                          ))}
                        </div>
                        <p className="text-xs text-fg-muted">
                          {chosen.length} file{chosen.length !== 1 ? 's' : ''}{' '}
                          selected · click or drop to replace
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}

            {error && <p className="text-sm text-danger">{error}</p>}
          </form>
        </div>

        {/* Sticky footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-border shrink-0">
          <Button variant="default" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button
            variant="primary"
            type="submit"
            form="wf-run-form"
            disabled={isPending}
          >
            {isPending ? 'Queuing…' : 'Run'}
          </Button>
        </div>
      </div>
    </div>
  )
}
