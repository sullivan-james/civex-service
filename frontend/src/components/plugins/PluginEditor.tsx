import { useId, useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { usePluginSource, useSavePlugin } from '../../hooks/usePlugins'
import { useTheme } from '../../hooks/useTheme'
import {
  Button,
  Input,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
} from '../ui'

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
  const nameId = useId()
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
    <Modal onClose={onClose} size="xl" className="h-[90vh]">
      <ModalHeader onClose={onClose}>
        {isNew ? 'New plugin' : `Edit — ${initialFilename}`}
      </ModalHeader>

      <ModalBody className="flex flex-col gap-3">
        {isNew && (
          <div className="flex flex-col gap-1">
            <label
              htmlFor={nameId}
              className="text-xs font-medium text-fg-muted"
            >
              Plugin filename
            </label>
            <div className="flex items-center gap-1">
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
          <pre className="text-xs text-danger bg-danger-subtle border border-danger-subtle-border rounded-md p-2 whitespace-pre-wrap">
            {saveError}
          </pre>
        )}
      </ModalBody>

      <ModalFooter>
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
      </ModalFooter>
    </Modal>
  )
}
