import { useId, useState, useRef, useCallback } from 'react'
import CodeMirror, {
  type EditorView,
  type ViewUpdate,
} from '@uiw/react-codemirror'
import { yaml } from '@codemirror/lang-yaml'
import { useWorkflow, useSaveWorkflow } from '../../hooks/useWorkflows'
import {
  Button,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Input,
} from '../ui'
import { AutocompleteMenu } from './YamlAutocomplete'
import {
  getAutocompleteContext,
  getSuggestions,
  type Suggestion,
} from '../../utils/workflowAutocomplete'
import {
  groupWorkflowValidationErrors,
  findStepLine,
  type WorkflowValidationIssue,
} from '../../utils/workflowValidationErrors'
import { ApiError } from '../../api/client'
import type { PluginInfo } from '../../api/plugins'
import { useTheme } from '../../hooks/useTheme'

export const NEW_WORKFLOW_TEMPLATE = `name: my-workflow
description: null

triggers:
  record_created:
    schema: MySchema
  # record_updated:
  #   schema: MySchema
  #   fields:
  #     - my_field

steps:
  - id: load_bytes
    plugin: civex.load_file
    config:
      field: my_file_field

  - id: parse_csv
    plugin: civex.load_csv
    config:
      delimiter: ","
    inputs:
      bytes: load_bytes.bytes
`

interface WorkflowEditorModalProps {
  stem: string
  isNew: boolean
  onClose: () => void
  plugins: PluginInfo[]
}

export function WorkflowEditorModal({
  stem: initialStem,
  isNew,
  onClose,
  plugins,
}: WorkflowEditorModalProps) {
  const stemId = useId()
  const [stem, setStem] = useState(initialStem)
  const [content, setContent] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<WorkflowValidationIssue[] | null>(
    null,
  )
  const { resolved: theme } = useTheme()

  const { data: detail, isLoading } = useWorkflow(isNew ? '' : initialStem)
  const save = useSaveWorkflow()

  // Populate content once loaded
  if (!isNew && detail && content === null) {
    setContent(detail.content)
  }
  if (isNew && content === null) {
    setContent(NEW_WORKFLOW_TEMPLATE)
  }

  // Autocomplete (CIVEX-122) — plugin ids, config keys, step output refs,
  // driven off the same Story 3 plugin schema the contract panel below reads.
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [activeIndex, setActiveIndex] = useState(0)
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 })
  const acContextRef = useRef<{
    replaceFrom: number
    replaceTo: number
  } | null>(null)
  const viewRef = useRef<EditorView | null>(null)
  const editorWrapRef = useRef<HTMLDivElement>(null)
  // Suppresses the onUpdate-driven refresh for the dispatch applySuggestion
  // itself issues, so accepting a suggestion doesn't immediately reopen the menu.
  const applyingSuggestionRef = useRef(false)

  const refreshSuggestions = useCallback(
    (text: string, cursor: number) => {
      const ctx = getAutocompleteContext(text, cursor)
      const matches = ctx ? getSuggestions(ctx, plugins, text) : []
      if (!ctx || matches.length === 0) {
        acContextRef.current = null
        setSuggestions([])
        return
      }
      acContextRef.current = ctx
      setSuggestions(matches)
      setActiveIndex(0)
      const view = viewRef.current
      const wrap = editorWrapRef.current
      const coords = view?.coordsAtPos(cursor)
      if (coords && wrap) {
        const wrapRect = wrap.getBoundingClientRect()
        setMenuPos({
          top: coords.bottom - wrapRect.top,
          left: coords.left - wrapRect.left,
        })
      }
    },
    [plugins],
  )

  const applySuggestion = useCallback(
    (index: number) => {
      const ctx = acContextRef.current
      const chosen = suggestions[index]
      const view = viewRef.current
      if (!ctx || !chosen || !view) return
      const newCursor = ctx.replaceFrom + chosen.insertText.length
      applyingSuggestionRef.current = true
      view.dispatch({
        changes: {
          from: ctx.replaceFrom,
          to: ctx.replaceTo,
          insert: chosen.insertText,
        },
        selection: { anchor: newCursor },
      })
      acContextRef.current = null
      setSuggestions([])
      view.focus()
    },
    [suggestions],
  )

  const handleUpdate = useCallback(
    (update: ViewUpdate) => {
      viewRef.current = update.view
      if (applyingSuggestionRef.current) {
        applyingSuggestionRef.current = false
        return
      }
      if (!update.docChanged && !update.selectionSet) return
      refreshSuggestions(
        update.state.doc.toString(),
        update.state.selection.main.head,
      )
    },
    [refreshSuggestions],
  )

  // Intercepted in the capture phase so the keys never reach CodeMirror's
  // own keymap (e.g. Tab-to-indent) while the suggestion menu is open.
  const handleEditorKeyDownCapture = useCallback(
    (e: React.KeyboardEvent) => {
      if (suggestions.length === 0) return
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        e.stopPropagation()
        setActiveIndex((i) => (i + 1) % suggestions.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        e.stopPropagation()
        setActiveIndex((i) => (i - 1 + suggestions.length) % suggestions.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        e.stopPropagation()
        applySuggestion(activeIndex)
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        setSuggestions([])
        return
      }
    },
    [suggestions, activeIndex, applySuggestion],
  )

  async function handleSave() {
    if (!stem.trim() || content === null) return
    setSaveError(null)
    try {
      await save.mutateAsync({ stem: stem.trim(), content })
      onClose()
    } catch (err) {
      // Contract violations (CIVEX-109) arrive as structured per-step
      // issues; anything else (bad stem, unparseable YAML) is a plain
      // string -- shown as a single general issue.
      if (err instanceof ApiError && Array.isArray(err.detail)) {
        setSaveError(err.detail as WorkflowValidationIssue[])
      } else {
        setSaveError([
          {
            step: null,
            message: err instanceof Error ? err.message : 'Save failed',
          },
        ])
      }
    }
  }

  // Jumps the editor's selection to a failing step's `id:` line, so a
  // structured error can be clicked to find the step it's about instead of
  // hunting for it in the YAML by hand.
  function jumpToStep(stepId: string) {
    const view = viewRef.current
    if (!view || content === null) return
    const lineNumber = findStepLine(content, stepId)
    if (lineNumber === null) return
    const line = view.state.doc.line(lineNumber)
    view.dispatch({
      selection: { anchor: line.from, head: line.to },
      scrollIntoView: true,
    })
    view.focus()
  }

  return (
    <Modal onClose={onClose} size="xl" className="h-[90vh]">
      <ModalHeader onClose={onClose}>
        {isNew ? 'New workflow' : `Edit — ${initialStem}.yaml`}
      </ModalHeader>

      <ModalBody className="flex flex-col gap-3">
        {isNew && (
          <div className="flex flex-col gap-1">
            <label
              htmlFor={stemId}
              className="text-xs font-medium text-fg-muted"
            >
              Filename stem
            </label>
            <div className="flex items-center gap-1">
              <Input
                id={stemId}
                aria-describedby={`${stemId}-hint`}
                type="text"
                value={stem}
                onChange={(e) =>
                  setStem(e.target.value.replace(/[^a-zA-Z0-9_-]/g, ''))
                }
                placeholder="my-workflow"
                className="flex-1"
              />
              <span className="text-sm text-fg-muted">.yaml</span>
            </div>
            <p id={`${stemId}-hint`} className="text-xs text-fg-subtle">
              Letters, numbers, hyphens and underscores only.
            </p>
          </div>
        )}

        {isLoading ? (
          <div className="flex-1 flex items-center justify-center text-sm text-fg-muted">
            Loading…
          </div>
        ) : (
          <div className="flex-1 flex flex-col min-h-0">
            <span className="text-xs font-medium text-fg mb-1">YAML</span>
            {isNew && (
              <p className="text-xs text-fg-subtle mb-1">
                A trigger tells civex when to run this workflow automatically —
                e.g. whenever a record of a given schema is created.
              </p>
            )}
            <div
              ref={editorWrapRef}
              onKeyDownCapture={handleEditorKeyDownCapture}
              className="relative flex-1 min-h-0 overflow-auto border border-border rounded-md bg-canvas-subtle focus-within:border-accent focus-within:ring-1 focus-within:ring-accent"
              style={{ minHeight: '200px' }}
            >
              <CodeMirror
                value={content ?? ''}
                theme={theme}
                onChange={(value) => setContent(value)}
                onUpdate={handleUpdate}
                onCreateEditor={(view) => {
                  viewRef.current = view
                }}
                onBlur={() => setSuggestions([])}
                extensions={[yaml()]}
                basicSetup={{ tabSize: 2 }}
                indentWithTab
                height="100%"
                className="h-full text-xs"
                style={{ height: '100%' }}
              />
              <AutocompleteMenu
                suggestions={suggestions}
                activeIndex={activeIndex}
                position={menuPos}
                onSelect={applySuggestion}
              />
            </div>
          </div>
        )}

        {saveError && (
          <div className="text-xs bg-danger-subtle border border-danger-subtle-border rounded-md p-2 max-h-40 overflow-auto space-y-2">
            {groupWorkflowValidationErrors(saveError).map(
              ({ step, messages }) => (
                <div key={step ?? '__general__'}>
                  {step ? (
                    <button
                      type="button"
                      onClick={() => jumpToStep(step)}
                      className="font-mono font-semibold text-danger hover:underline"
                    >
                      Step '{step}'
                    </button>
                  ) : (
                    <span className="font-semibold text-danger">General</span>
                  )}
                  <ul className="list-disc list-inside text-danger">
                    {messages.map((message, i) => (
                      <li key={i} className="whitespace-pre-wrap">
                        {message}
                      </li>
                    ))}
                  </ul>
                </div>
              ),
            )}
          </div>
        )}
      </ModalBody>

      <ModalFooter>
        <Button variant="default" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={handleSave}
          disabled={save.isPending || !stem.trim()}
        >
          {save.isPending ? 'Saving…' : 'Save'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
