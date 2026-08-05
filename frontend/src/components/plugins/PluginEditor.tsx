import { useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { usePluginSource, useSavePlugin } from '../../hooks/usePlugins'
import { useTheme } from '../../hooks/useTheme'
import { Button } from '../ui'

const NEW_PLUGIN_TEMPLATE = `#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["civex-plugin-sdk"]
# ///
from pydantic import BaseModel
from civex_plugin_sdk import Ctx, Plugin as PluginBase, serve


class Plugin(PluginBase):
    id = "my_project.my_plugin"
    name = "My Plugin"
    category = "transforms"
    capabilities = []

    class Config(BaseModel):
        pass

    def invoke(self, inputs: dict, config: Config, ctx: Ctx) -> dict:
        return {}


if __name__ == "__main__":
    serve(Plugin)
`

interface Props {
  filename: string
  isNew: boolean
  onClose: () => void
}

export function PluginEditor({
  filename: initialFilename,
  isNew,
  onClose,
}: Props) {
  const [name, setName] = useState(
    isNew ? '' : initialFilename.replace(/\.py$/, ''),
  )
  const [code, setCode] = useState<string | null>(
    isNew ? NEW_PLUGIN_TEMPLATE : null,
  )
  const [saveError, setSaveError] = useState<string | null>(null)
  const { resolved: theme } = useTheme()

  const { data: source, isLoading } = usePluginSource(
    isNew ? '' : initialFilename,
  )
  const save = useSavePlugin()

  if (!isNew && source && code === null) {
    setCode(source.code)
  }

  async function handleSave() {
    if (!name.trim() || code === null) return
    setSaveError(null)
    try {
      await save.mutateAsync({ name: name.trim(), code })
      onClose()
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed')
    }
  }

  return (
    <div className="fixed inset-0 bg-overlay-scrim flex items-center justify-center z-50 p-4">
      <div
        className="bg-canvas rounded-lg shadow-xl w-full max-w-3xl flex flex-col"
        style={{ height: '90vh' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <h2 className="text-base font-semibold text-fg">
            {isNew ? 'New plugin' : `Edit — ${initialFilename}`}
          </h2>
          <button
            onClick={onClose}
            className="text-fg-muted hover:text-fg text-xl leading-none"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="flex flex-col gap-3 p-5 flex-1 min-h-0">
          {isNew && (
            <label className="block">
              <span className="text-xs font-medium text-fg">
                Plugin filename
              </span>
              <div className="flex items-center gap-1 mt-1">
                <input
                  type="text"
                  value={name}
                  onChange={(e) =>
                    setName(
                      e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''),
                    )
                  }
                  placeholder="my_plugin"
                  className="border border-border rounded-md px-3 py-1.5 text-sm w-56 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
                />
                <span className="text-sm text-fg-muted">.py</span>
              </div>
              <p className="text-xs text-fg-muted mt-1">
                Lowercase letters, digits and underscores only.
              </p>
            </label>
          )}

          {isLoading ? (
            <div className="flex-1 flex items-center justify-center text-sm text-fg-muted">
              Loading…
            </div>
          ) : (
            <div className="flex-1 flex flex-col min-h-0">
              <span className="text-xs font-medium text-fg mb-1">Python</span>
              <div className="flex-1 min-h-0 border border-border rounded-md overflow-auto bg-canvas-subtle">
                <CodeMirror
                  value={code ?? ''}
                  height="100%"
                  theme={theme}
                  extensions={[python()]}
                  onChange={(value) => setCode(value)}
                  basicSetup={{ tabSize: 4 }}
                  style={{ fontSize: '0.75rem', height: '100%' }}
                />
              </div>
            </div>
          )}

          {saveError && (
            <pre className="text-xs text-danger bg-danger-subtle border border-danger-subtle-border rounded p-2 whitespace-pre-wrap">
              {saveError}
            </pre>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-border">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleSave}
            disabled={save.isPending || !name.trim()}
          >
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </div>
    </div>
  )
}
