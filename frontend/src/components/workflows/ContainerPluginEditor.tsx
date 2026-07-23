import { useState } from 'react'
import {
  useContainerPlugin,
  useSaveContainerPluginFile,
} from '../../hooks/useContainerPlugins'
import { Button } from '../ui'
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

  const [contents, setContents] = useState<Record<string, string> | null>(
    null,
  )
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [buildResult, setBuildResult] = useState<BuildResult | null>(null)

  // Populate content once loaded
  if (detail && contents === null) {
    setContents(detail.files)
    setSelectedPath(
      'Dockerfile' in detail.files ? 'Dockerfile' : Object.keys(detail.files)[0],
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
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-5xl flex flex-col"
        style={{ height: '90vh' }}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#d0d7de]">
          <h2 className="text-base font-semibold text-[#1f2328]">
            Container plugin — {name}
          </h2>
          <button
            onClick={onClose}
            className="text-[#656d76] hover:text-[#1f2328] text-xl leading-none"
          >
            ×
          </button>
        </div>

        {isLoading || contents === null ? (
          <div className="flex-1 flex items-center justify-center text-sm text-[#656d76]">
            Loading…
          </div>
        ) : (
          <div className="flex flex-1 min-h-0">
            {/* File tree */}
            <div className="w-56 border-r border-[#d0d7de] overflow-y-auto py-2">
              {filePaths.map((path) => (
                <button
                  key={path}
                  onClick={() => setSelectedPath(path)}
                  className={`block w-full text-left px-3 py-1.5 text-xs font-mono truncate ${
                    path === selectedPath
                      ? 'bg-[#ddf4ff] text-[#0969da]'
                      : 'text-[#1f2328] hover:bg-[#f6f8fa]'
                  }`}
                >
                  {path}
                </button>
              ))}
            </div>

            {/* Editor */}
            <div className="flex-1 flex flex-col min-h-0 p-4 gap-3">
              <span className="text-xs font-medium text-[#1f2328]">
                {selectedPath}
              </span>
              <textarea
                value={selectedPath ? contents[selectedPath] : ''}
                onChange={(e) =>
                  selectedPath &&
                  setContents({ ...contents, [selectedPath]: e.target.value })
                }
                spellCheck={false}
                className="flex-1 min-h-0 font-mono text-xs border border-[#d0d7de] rounded-md p-3 resize-none bg-[#f6f8fa] focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da] leading-relaxed"
              />

              {buildResult && (
                <div
                  className={`text-xs rounded p-2 whitespace-pre-wrap max-h-32 overflow-y-auto ${
                    buildResult.success
                      ? 'text-[#1a7f37] bg-[#dafbe1] border border-[#1a7f37]/30'
                      : 'text-red-600 bg-red-50 border border-red-200'
                  }`}
                >
                  {buildResult.success ? 'Build succeeded' : 'Build failed'}
                  {buildResult.log ? `\n\n${buildResult.log}` : ''}
                </div>
              )}
            </div>
          </div>
        )}

        <div className="flex justify-end gap-2 px-5 py-4 border-t border-[#d0d7de]">
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
        </div>
      </div>
    </div>
  )
}
