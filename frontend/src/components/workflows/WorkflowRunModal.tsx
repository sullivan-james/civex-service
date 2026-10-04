import { useState } from 'react'
import { useNavigate } from 'react-router'
import {
  useRunWorkflow,
  useRunWorkflowWithFiles,
} from '../../hooks/useWorkflows'
import {
  Button,
  Field,
  FileDropZone,
  Input,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
} from '../ui'
import type { Workflow } from '../../api/workflows'

interface Props {
  workflow: Workflow
  /** The record to run it for, when started from that record's page. The
   * person is already on the record, so it is not asked for or shown. Without
   * it, a record ID is asked for. */
  recordId?: string
  /** Called once the run has been queued, before the dialog closes. */
  onStarted?: () => void
  onClose: () => void
}

export function WorkflowRunModal({
  workflow,
  recordId: prefilled,
  onStarted,
  onClose,
}: Props) {
  const navigate = useNavigate()
  const [recordId, setRecordId] = useState(prefilled ?? '')
  const [fileInputs, setFileInputs] = useState<Record<string, File[]>>({})
  const [error, setError] = useState<string | null>(null)

  const runPlain = useRunWorkflow()
  const runFiles = useRunWorkflowWithFiles()

  const filesInputs = Object.entries(workflow.inputs ?? {}).filter(
    ([, v]) => v.type === 'files',
  )
  const hasFileInputs = filesInputs.length > 0
  const isPending = runPlain.isPending || runFiles.isPending

  function handleFiles(inputName: string, files: File[]) {
    setFileInputs((prev) => ({ ...prev, [inputName]: files }))
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
      onStarted?.()
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
          {!prefilled && (
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
                autoFocus
                type="text"
                value={recordId}
                onChange={(e) => setRecordId(e.target.value)}
                placeholder="Short ID or full UUID"
                className="w-full font-mono"
              />
            </Field>
          )}

          {filesInputs.map(([inputName, decl]) => {
            const chosen = fileInputs[inputName] ?? []
            const dropzoneLabel = decl.label ?? inputName
            return (
              <div key={inputName} className="flex flex-col gap-1">
                <span className="text-xs font-medium text-fg-muted">
                  {dropzoneLabel}
                </span>
                <FileDropZone
                  multiple
                  inputLabel={`${dropzoneLabel}: choose files`}
                  onFiles={(files) => handleFiles(inputName, files)}
                >
                  {chosen.length === 0 ? undefined : (
                    <span className="block text-left">
                      <span className="mb-1 block max-h-32 space-y-1 overflow-y-auto">
                        {chosen.map((f, i) => (
                          <span
                            key={i}
                            className="block truncate font-mono text-xs text-fg"
                          >
                            {f.name}
                          </span>
                        ))}
                      </span>
                      <span className="block text-xs text-fg-muted">
                        {chosen.length} file{chosen.length !== 1 ? 's' : ''}{' '}
                        selected · click or drop to replace
                      </span>
                    </span>
                  )}
                </FileDropZone>
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
