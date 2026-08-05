import { useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { usePluginSource, useSavePlugin } from '../../hooks/usePlugins'
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
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-3xl flex flex-col"
        style={{ height: '90vh' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#d0d7de]">
          <h2 className="text-base font-semibold text-[#1f2328]">
            {isNew ? 'New plugin' : `Edit — ${initialFilename}`}
          </h2>
          <button
            onClick={onClose}
            className="text-[#656d76] hover:text-[#1f2328] text-xl leading-none"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="flex flex-col gap-3 p-6 flex-1 min-h-0">
          {isNew && (
            <label className="block">
              <span className="text-xs font-medium text-[#1f2328]">
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
                  className="border border-[#d0d7de] rounded-md px-3 py-2 text-sm w-56 focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
                />
                <span className="text-sm text-[#656d76]">.py</span>
              </div>
              <p className="text-xs text-[#656d76] mt-1">
                Lowercase letters, digits and underscores only.
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
                Python
              </span>
              <div className="flex-1 min-h-0 border border-[#d0d7de] rounded-md overflow-auto bg-[#f6f8fa]">
                <CodeMirror
                  value={code ?? ''}
                  height="100%"
                  extensions={[python()]}
                  onChange={(value) => setCode(value)}
                  basicSetup={{ tabSize: 4 }}
                  style={{ fontSize: '0.75rem', height: '100%' }}
                />
              </div>
            </div>
          )}

          {saveError && (
            <pre className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-md p-2 whitespace-pre-wrap">
              {saveError}
            </pre>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-[#d0d7de]">
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
