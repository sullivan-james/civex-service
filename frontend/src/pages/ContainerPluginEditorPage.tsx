import { useState } from 'react'
import { useParams } from 'react-router'
import {
  useContainerPlugin,
  useSaveContainerPluginFile,
} from '../hooks/useContainerPlugins'
import { useCloseOrBack } from '../hooks/useCloseOrBack'
import { Button, Field, Page, Textarea } from '../components/ui'
import type { BuildResult } from '../api/containerPlugins'

/** Multi-file editor for a Tier 2 (container) plugin: a Dockerfile + source
 * tree. Saving a file triggers an immediate `docker build` and shows the
 * result inline — the container-tier equivalent of the Tier 1 .py editor's
 * save-triggers-describe round-trip. Stays on the page after a save (unlike
 * the workflow/plugin editors) since a multi-file plugin is typically saved
 * file-by-file and the build result is worth seeing before moving on. */
export default function ContainerPluginEditorPage() {
  const { name = '' } = useParams<{ name: string }>()
  const closeOrBack = useCloseOrBack('/plugins')
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
    <Page
      breadcrumbs={[{ label: 'Plugins', to: '/plugins' }, { label: name }]}
      title={`Container plugin — ${name}`}
      action={
        <div className="flex items-center gap-2">
          <Button variant="default" onClick={() => closeOrBack()}>
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
      }
    >
      {isLoading || contents === null ? (
        <div className="flex items-center justify-center text-sm text-fg-muted h-[65vh]">
          Loading…
        </div>
      ) : (
        <div className="flex h-[65vh] border border-border rounded-md overflow-hidden">
          {/* File tree */}
          <div className="w-56 border-r border-border overflow-y-auto py-2">
            {filePaths.map((path) => (
              <button
                key={path}
                onClick={() => setSelectedPath(path)}
                className={`block w-full text-left px-3 py-2 text-xs font-mono truncate ${
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
            <Field
              label={selectedPath ?? 'File contents'}
              hideLabel
              className="flex-1 min-h-0"
            >
              <Textarea
                size="sm"
                value={selectedPath ? contents[selectedPath] : ''}
                onChange={(e) =>
                  selectedPath &&
                  setContents({ ...contents, [selectedPath]: e.target.value })
                }
                spellCheck={false}
                className="h-full font-mono resize-none bg-canvas-subtle leading-relaxed"
              />
            </Field>

            {buildResult && (
              <div
                role="alert"
                className={`text-xs rounded-md p-2 whitespace-pre-wrap max-h-32 overflow-y-auto ${
                  buildResult.success
                    ? 'text-success bg-success-subtle border border-success/30'
                    : 'text-danger bg-danger-subtle border border-danger-subtle-border'
                }`}
              >
                {buildResult.success ? 'Build succeeded' : 'Build failed'}
                {buildResult.log ? `\n\n${buildResult.log}` : ''}
              </div>
            )}
          </div>
        </div>
      )}
    </Page>
  )
}
