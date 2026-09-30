import { useId, useState } from 'react'
import { useParams } from 'react-router'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { usePluginSource, useSavePlugin } from '../hooks/usePlugins'
import { useTheme } from '../hooks/useTheme'
import { useCloseOrBack } from '../hooks/useCloseOrBack'
import { Button, Input, Page } from '../components/ui'

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

interface PluginEditorPageProps {
  isNew?: boolean
}

export default function PluginEditorPage({
  isNew = false,
}: PluginEditorPageProps) {
  const { stem: routeStem } = useParams<{ stem: string }>()
  const initialFilename = isNew ? '' : `${routeStem ?? ''}.py`
  const nameId = useId()
  const [name, setName] = useState(isNew ? '' : (routeStem ?? ''))
  const [code, setCode] = useState<string | null>(
    isNew ? NEW_PLUGIN_TEMPLATE : null,
  )
  const [saveError, setSaveError] = useState<string | null>(null)
  const { resolved: theme } = useTheme()
  const closeOrBack = useCloseOrBack('/plugins')

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
      closeOrBack()
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed')
    }
  }

  return (
    <Page
      breadcrumbs={[
        { label: 'Plugins', to: '/plugins' },
        { label: isNew ? 'New plugin' : initialFilename },
      ]}
      title={isNew ? 'New plugin' : `Edit — ${initialFilename}`}
      action={
        <div className="flex items-center gap-2">
          <Button variant="default" onClick={() => closeOrBack()}>
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
      }
    >
      <div className="flex flex-col gap-3">
        {isNew && (
          <div className="flex flex-col gap-1">
            <label
              htmlFor={nameId}
              className="text-xs font-medium text-fg-muted"
            >
              Plugin filename
            </label>
            <div className="flex items-center gap-1 max-w-sm">
              <Input
                id={nameId}
                aria-describedby={`${nameId}-hint`}
                type="text"
                value={name}
                onChange={(e) =>
                  setName(
                    e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''),
                  )
                }
                placeholder="my_plugin"
                className="flex-1"
              />
              <span className="text-sm text-fg-muted">.py</span>
            </div>
            <p id={`${nameId}-hint`} className="text-xs text-fg-subtle">
              Lowercase letters, digits and underscores only.
            </p>
          </div>
        )}

        {isLoading ? (
          <div className="flex-1 flex items-center justify-center text-sm text-fg-muted">
            Loading…
          </div>
        ) : (
          <div className="flex-1 flex flex-col min-h-0">
            <span className="text-xs font-medium text-fg mb-1">Python</span>
            <div className="flex-1 min-h-0 h-[65vh] border border-border rounded-md overflow-auto bg-canvas-subtle">
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
          <pre className="text-xs text-danger bg-danger-subtle border border-danger-subtle-border rounded-md p-2 whitespace-pre-wrap">
            {saveError}
          </pre>
        )}
      </div>
    </Page>
  )
}
