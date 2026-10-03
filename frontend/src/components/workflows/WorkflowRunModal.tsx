import { useState, useRef } from 'react'
import { useNavigate } from 'react-router'
import {
  useRunWorkflow,
  useRunWorkflowWithFiles,
} from '../../hooks/useWorkflows'
import {
  Button,
  Field,
  Input,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
} from '../ui'
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
    <Modal onClose={onClose}>
      <ModalHeader>
        Run <span className="font-mono">{workflow.name}</span>
      </ModalHeader>

      <ModalBody>
        <form id="wf-run-form" onSubmit={handleSubmit} className="space-y-4">
          <Field
            label={
              <>
                Record ID
                {workflow.record_schema && (
                  <span className="ml-2 text-xs text-fg-muted font-normal">
                    ({workflow.record_schema})
                  </span>
                )}
              </>
            }
            required
          >
            <Input
              autoFocus={!prefilled}
              type="text"
              value={recordId}
              onChange={(e) => setRecordId(e.target.value)}
              placeholder="Short ID or full UUID"
              readOnly={!!prefilled}
              className={`w-full font-mono ${prefilled ? 'bg-canvas-subtle text-fg-muted' : ''}`}
            />
          </Field>

          {filesInputs.map(([inputName, decl]) => {
            const chosen = fileInputs[inputName] ?? []
            const dropzoneLabel = decl.label ?? inputName
            return (
              <div key={inputName} className="flex flex-col gap-1">
                <span className="text-xs font-medium text-fg-muted">
                  {dropzoneLabel}
                </span>
                <input
                  ref={(el) => {
                    fileRefs.current[inputName] = el
                  }}
                  type="file"
                  multiple
                  tabIndex={-1}
                  aria-hidden="true"
                  className="hidden"
                  onChange={(e) => handleFileChange(inputName, e.target.files)}
                />
                <div
                  role="button"
                  tabIndex={0}
                  aria-label={`${dropzoneLabel} — drop files here or browse`}
                  className="border-2 border-dashed border-border rounded-md px-4 py-6 text-center cursor-pointer hover:border-accent hover:bg-canvas-subtle transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  onClick={() => fileRefs.current[inputName]?.click()}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      fileRefs.current[inputName]?.click()
                    }
                  }}
                  onDragOver={(e) => {
                    e.preventDefault()
                    e.dataTransfer.dropEffect = 'copy'
                  }}
                  onDrop={(e) => {
                    e.preventDefault()
                    handleFileChange(inputName, e.dataTransfer.files)
                  }}
                >
                  {chosen.length === 0 ? (
                    <p className="text-sm text-fg-muted">
                      Drop files here or{' '}
                      <span className="text-accent">browse</span>
                    </p>
                  ) : (
                    <div className="text-left">
                      <div className="max-h-32 overflow-y-auto space-y-1 mb-1">
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

          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
        </form>
      </ModalBody>

      <ModalFooter>
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
      </ModalFooter>
    </Modal>
  )
}
