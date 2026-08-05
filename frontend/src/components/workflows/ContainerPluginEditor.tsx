import { useState } from 'react'
import {
  useContainerPlugin,
  useSaveContainerPluginFile,
} from '../../hooks/useContainerPlugins'
import { Button, Modal, ModalBody, ModalFooter, ModalHeader } from '../ui'
import type { BuildResult } from '../../api/containerPlugins'

interface ContainerPluginEditorProps {
  name: string
  onClose: () => void
}

/** Multi-file editor for a Tier 2 (container) plugin: a Dockerfile + source
 * tree. Saving a file triggers an immediate `docker build` and shows the
 * result inline — the container-tier equivalent of the Tier 1 .py editor's
 * save-triggers-describe round-trip. */
export function ContainerPluginEditor({
  name,
  onClose,
}: ContainerPluginEditorProps) {
  const { data: detail, isLoading } = useContainerPlugin(name)
  const save = useSaveContainerPluginFile()

  const [contents, setContents] = useState<Record<string, string> | null>(null)
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [buildResult, setBuildResult] = useState<BuildResult | null>(null)

  // Populate content once loaded
  if (detail && contents === null) {
    setContents(detail.files)
    setSelectedPath(
      'Dockerfile' in detail.files
        ? 'Dockerfile'
        : Object.keys(detail.files)[0],
    )
  }

  async function handleSave() {
    if (!selectedPath || contents === null) return
    setBuildResult(null)
    const result = await save.mutateAsync({
      name,
      path: selectedPath,
      content: contents[selectedPath],
    })
    setBuildResult(result)
  }

  const filePaths = contents ? Object.keys(contents).sort() : []

  return (
    <Modal onClose={onClose} size="2xl" className="h-[90vh]">
      <ModalHeader onClose={onClose}>Container plugin — {name}</ModalHeader>

      {isLoading || contents === null ? (
        <ModalBody className="flex items-center justify-center text-sm text-fg-muted">
          Loading…
        </ModalBody>
      ) : (
        <ModalBody padded={false} className="flex">
          {/* File tree */}
          <div className="w-56 border-r border-border overflow-y-auto py-2">
            {filePaths.map((path) => (
              <button
                key={path}
                onClick={() => setSelectedPath(path)}
                className={`block w-full text-left px-3 py-1.5 text-xs font-mono truncate ${
                  path === selectedPath
                    ? 'bg-accent-subtle text-accent'
                    : 'text-fg hover:bg-canvas-subtle'
                }`}
              >
                {path}
              </button>
            ))}
          </div>

          {/* Editor */}
          <div className="flex-1 flex flex-col min-h-0 p-4 gap-3">
            <span className="text-xs font-medium text-fg">{selectedPath}</span>
            <textarea
              value={selectedPath ? contents[selectedPath] : ''}
              onChange={(e) =>
                selectedPath &&
                setContents({ ...contents, [selectedPath]: e.target.value })
              }
              spellCheck={false}
              className="flex-1 min-h-0 font-mono text-xs border border-border rounded-md p-3 resize-none bg-canvas-subtle focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent leading-relaxed"
            />

            {buildResult && (
              <div
                className={`text-xs rounded p-2 whitespace-pre-wrap max-h-32 overflow-y-auto ${
                  buildResult.success
                    ? 'text-success bg-success-subtle border border-success/30'
                    : 'text-red-600 bg-red-50 border border-red-200'
                }`}
              >
                {buildResult.success ? 'Build succeeded' : 'Build failed'}
                {buildResult.log ? `\n\n${buildResult.log}` : ''}
              </div>
            )}
          </div>
        </ModalBody>
      )}

      <ModalFooter>
        <Button variant="default" onClick={onClose}>
          Close
        </Button>
        <Button
          variant="primary"
          onClick={handleSave}
          disabled={save.isPending || !selectedPath}
        >
          {save.isPending ? 'Saving & rebuilding…' : 'Save & rebuild'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
