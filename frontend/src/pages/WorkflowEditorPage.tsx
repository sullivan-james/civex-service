import { useCallback, useId, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router'
import CodeMirror, {
  type EditorView,
  type ViewUpdate,
} from '@uiw/react-codemirror'
import { yaml } from '@codemirror/lang-yaml'
import {
  useSaveWorkflow,
  useWorkflow,
  useWorkflows,
} from '../hooks/useWorkflows'
import { usePlugins } from '../hooks/usePlugins'
import { useSchemas } from '../hooks/useSchemas'
import { useCollections } from '../hooks/useCollections'
import { useCloseOrBack } from '../hooks/useCloseOrBack'
import {
  Button,
  CheckRow,
  Input,
  Page,
  SegmentedControl,
} from '../components/ui'
import { AutocompleteMenu } from '../components/workflows/YamlAutocomplete'
import { WorkflowBuilder } from '../components/workflows/builder/WorkflowBuilder'
import { TemplatePicker } from '../components/workflows/builder/TemplatePicker'
import { TrialPanel } from '../components/workflows/TrialPanel'
import {
  getAutocompleteContext,
  getSuggestions,
  type Suggestion,
} from '../utils/workflowAutocomplete'
import {
  findStepLine,
  groupWorkflowValidationErrors,
  type WorkflowValidationIssue,
} from '../utils/workflowValidationErrors'
import {
  readDraft,
  stemFor,
  writeDraft,
  type WorkflowDraft,
} from '../utils/workflowModel'
import { WORKFLOW_TEMPLATES } from '../utils/workflowTemplates'
import { missingSettings } from '../utils/pluginSettings'
import type { PluginInfo } from '../api/plugins'
import type { WorkflowInput } from '../api/workflows'
import { ApiError } from '../api/client'
import { useTheme } from '../hooks/useTheme'

type Mode = 'builder' | 'yaml'

/** What is still to choose before it can be saved, counted the way the
 * builder marks it. */
function unfinished(draft: WorkflowDraft, plugins: PluginInfo[]): number {
  let n = draft.name.trim() ? 0 : 1
  if (!draft.schema) n++
  for (const step of draft.steps) {
    const plugin = plugins.find((p) => p.id === step.plugin)
    if (!step.plugin) {
      n++
      continue
    }
    n += missingSettings(step, plugin).length
    n += (plugin?.inputs ?? []).filter(
      (i) => i.required && !step.inputs[i.name],
    ).length
  }
  return n
}

function issuesByStep(issues: WorkflowValidationIssue[] | null) {
  const out = new Map<string, string[]>()
  for (const g of groupWorkflowValidationErrors(issues ?? [])) {
    out.set(g.step ?? '', g.messages)
  }
  return out
}

/** The YAML, with autocomplete of plugin ids, config keys and step outputs. */
function YamlEditor({
  content,
  onChange,
  plugins,
  viewRef,
}: {
  content: string
  onChange: (value: string) => void
  plugins: PluginInfo[]
  viewRef: React.RefObject<EditorView | null>
}) {
  const { resolved: theme } = useTheme()
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [activeIndex, setActiveIndex] = useState(0)
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 })
  const acContextRef = useRef<{
    replaceFrom: number
    replaceTo: number
  } | null>(null)
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
    [plugins, viewRef],
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
    [suggestions, viewRef],
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
    [refreshSuggestions, viewRef],
  )

  // Intercepted in the capture phase so the keys never reach CodeMirror's
  // own keymap (e.g. Tab-to-indent) while the suggestion menu is open.
  const handleKeyDownCapture = useCallback(
    (e: React.KeyboardEvent) => {
      if (suggestions.length === 0) return
      const stop = () => {
        e.preventDefault()
        e.stopPropagation()
      }
      if (e.key === 'ArrowDown') {
        stop()
        setActiveIndex((i) => (i + 1) % suggestions.length)
      } else if (e.key === 'ArrowUp') {
        stop()
        setActiveIndex((i) => (i - 1 + suggestions.length) % suggestions.length)
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        stop()
        applySuggestion(activeIndex)
      } else if (e.key === 'Escape') {
        stop()
        setSuggestions([])
      }
    },
    [suggestions, activeIndex, applySuggestion],
  )

  return (
    <div
      ref={editorWrapRef}
      onKeyDownCapture={handleKeyDownCapture}
      className="relative h-[65vh] min-h-0 overflow-auto rounded-md border border-border bg-canvas-subtle focus-within:border-accent focus-within:ring-1 focus-within:ring-accent"
    >
      <CodeMirror
        value={content}
        theme={theme}
        onChange={onChange}
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
  )
}

interface WorkflowEditorPageProps {
  isNew?: boolean
}

export default function WorkflowEditorPage({
  isNew = false,
}: WorkflowEditorPageProps) {
  const { stem: routeStem } = useParams<{ stem: string }>()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const initialStem = isNew ? '' : (routeStem ?? '')
  const stemId = useId()
  const [stemEdited, setStemEdited] = useState<string | null>(null)
  const [content, setContent] = useState<string | null>(null)
  const [mode, setMode] = useState<Mode>('builder')
  const [issues, setIssues] = useState<WorkflowValidationIssue[] | null>(null)
  const [showMissing, setShowMissing] = useState(false)
  const viewRef = useRef<EditorView | null>(null)
  const closeOrBack = useCloseOrBack('/workflows')

  const { data: plugins = [] } = usePlugins()
  const { data: schemas = [] } = useSchemas()
  const { data: collections = [] } = useCollections()
  const { data: existing = [] } = useWorkflows()
  const { data: detail, isLoading } = useWorkflow(isNew ? '' : initialStem)
  const save = useSaveWorkflow()

  const template = WORKFLOW_TEMPLATES.find(
    (t) => t.id === params.get('template'),
  )
  if (!isNew && detail && content === null) setContent(detail.content)
  if (isNew && template && content === null) {
    setContent(template.build(params.get('schema') ?? ''))
  }

  const read = useMemo(() => readDraft(content ?? ''), [content])
  const draft = read.ok ? read.draft : null
  // The builder shows only what it can read; otherwise the YAML is the way.
  const effectiveMode: Mode = draft ? mode : 'yaml'

  // A new workflow is saved under a name made from its own, never over another.
  const stem = useMemo(() => {
    if (!isNew) return initialStem
    if (stemEdited !== null) return stemEdited
    const base = stemFor(draft?.name ?? '')
    const taken = new Set(existing.map((w) => w.stem))
    if (!taken.has(base)) return base
    for (let n = 2; ; n++) if (!taken.has(`${base}-${n}`)) return `${base}-${n}`
  }, [isNew, initialStem, stemEdited, draft?.name, existing])

  function setDraft(next: WorkflowDraft) {
    setIssues(null)
    setContent((prev) => writeDraft(prev ?? '', next))
  }

  const errors = issuesByStep(issues)
  const toFinish = draft ? unfinished(draft, plugins) : 0

  async function handleSave() {
    if (!stem.trim() || content === null) return
    if (draft && toFinish > 0) {
      setShowMissing(true)
      return
    }
    setIssues(null)
    try {
      const saved = await save.mutateAsync({ stem: stem.trim(), content })
      if (isNew)
        navigate(`/workflows/${encodeURIComponent(saved.stem)}`, {
          replace: true,
        })
      else closeOrBack()
    } catch (err) {
      // Contract violations (CIVEX-109) arrive as structured per-step
      // issues; anything else (bad stem, unparseable YAML) is a plain
      // string -- shown as a single general issue.
      if (err instanceof ApiError && Array.isArray(err.detail)) {
        setIssues(err.detail as WorkflowValidationIssue[])
      } else {
        setIssues([
          {
            step: null,
            message: err instanceof Error ? err.message : 'Save failed',
          },
        ])
      }
    }
  }

  // In YAML, a step's problem can be clicked to select its `id:` line.
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

  const name = detail?.name ?? initialStem
  const breadcrumbs = [
    { label: 'Workflows', to: '/workflows' },
    ...(isNew
      ? [{ label: 'New workflow' }]
      : [
          { label: name, to: `/workflows/${encodeURIComponent(initialStem)}` },
          { label: 'Edit' },
        ]),
  ]

  if (isNew && !template) {
    return (
      <Page
        breadcrumbs={breadcrumbs}
        title="New workflow"
        info="Pick a starting point. Every choice opens the same builder, where anything can be changed."
      >
        <TemplatePicker
          onPick={(t) =>
            setParams(
              (p) => {
                const next = new URLSearchParams(p)
                next.set('template', t.id)
                return next
              },
              { replace: true },
            )
          }
        />
      </Page>
    )
  }

  // What it asks for when run: its own value inputs, and each Files step set
  // to be chosen then (named by the step).
  const inputs: Record<string, WorkflowInput> = {
    ...Object.fromEntries(
      (draft?.steps ?? [])
        .filter(
          (s) =>
            s.plugin.startsWith('civex.files') &&
            (s.config.source ?? 'run') === 'run',
        )
        .map((s) => [
          s.id,
          {
            type: 'files',
            label: typeof s.config.label === 'string' ? s.config.label : s.id,
            description: null,
          },
        ]),
    ),
    ...Object.fromEntries(
      (draft?.inputs ?? []).map((i) => [
        i.key,
        { type: i.type, label: i.label || null, description: null },
      ]),
    ),
  }
  const triggered = !!draft && (draft.onCreated || draft.onUpdated)

  return (
    <Page
      breadcrumbs={breadcrumbs}
      title={isNew ? 'New workflow' : name}
      action={
        <div className="flex items-center gap-2">
          {showMissing && toFinish > 0 && (
            <span className="text-sm text-danger">
              {toFinish} thing{toFinish === 1 ? '' : 's'} to choose
            </span>
          )}
          <Button onClick={() => closeOrBack()}>Cancel</Button>
          <Button
            variant="primary"
            onClick={handleSave}
            disabled={save.isPending || !stem.trim()}
          >
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      }
    >
      {isLoading ? (
        <p className="text-sm text-fg-muted">Loading…</p>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
          <div className="flex min-w-0 flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <SegmentedControl
                label="Edit as"
                value={effectiveMode}
                onChange={(m) => setMode(m)}
                options={[
                  { value: 'builder', label: 'Builder' },
                  { value: 'yaml', label: 'YAML' },
                ]}
              />
              {draft && triggered && (
                <CheckRow
                  compact
                  checked={draft.enabled}
                  onChange={(on) => setDraft({ ...draft, enabled: on })}
                  title={
                    draft.enabled
                      ? 'On: starts by itself'
                      : 'Off: runs only when someone starts it'
                  }
                />
              )}
            </div>
            {!read.ok && (
              <p className="rounded-md border border-attention-muted bg-attention-subtle p-3 text-sm">
                The builder can’t show this workflow ({read.problem}). Fix it in
                the YAML and the builder comes back.
              </p>
            )}
            {effectiveMode === 'builder' && draft ? (
              <WorkflowBuilder
                draft={draft}
                onChange={setDraft}
                plugins={plugins}
                schemas={schemas}
                collections={collections}
                errors={errors}
                showMissing={showMissing}
              />
            ) : (
              <>
                {isNew && (
                  <div className="flex max-w-sm items-center gap-1">
                    <label
                      htmlFor={stemId}
                      className="text-xs font-medium text-fg-muted"
                    >
                      File name
                    </label>
                    <Input
                      id={stemId}
                      size="sm"
                      value={stem}
                      onChange={(e) =>
                        setStemEdited(
                          e.target.value.replace(/[^a-zA-Z0-9_-]/g, ''),
                        )
                      }
                      className="flex-1 font-mono"
                    />
                    <span className="text-sm text-fg-muted">.yaml</span>
                  </div>
                )}
                <YamlEditor
                  content={content ?? ''}
                  onChange={(text) => {
                    setIssues(null)
                    setContent(text)
                  }}
                  plugins={plugins}
                  viewRef={viewRef}
                />
                {issues && (
                  <div className="max-h-40 space-y-2 overflow-auto rounded-md border border-danger-subtle-border bg-danger-subtle p-2 text-xs">
                    {groupWorkflowValidationErrors(issues).map(
                      ({ step, messages }) => (
                        <div key={step ?? '__general__'}>
                          {step ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              className="font-mono font-semibold text-danger"
                              onClick={() => jumpToStep(step)}
                            >
                              Step '{step}'
                            </Button>
                          ) : (
                            <span className="font-semibold text-danger">
                              General
                            </span>
                          )}
                          <ul className="list-inside list-disc text-danger">
                            {messages.map((m, i) => (
                              <li key={i} className="whitespace-pre-wrap">
                                {m}
                              </li>
                            ))}
                          </ul>
                        </div>
                      ),
                    )}
                  </div>
                )}
              </>
            )}
          </div>
          <div className="flex flex-col gap-2 lg:sticky lg:top-4">
            <TrialPanel
              content={content ?? ''}
              schema={draft?.schema ?? ''}
              inputs={inputs}
              plugins={plugins}
              ready={!!draft && toFinish === 0}
              waiting={
                draft
                  ? `Choose ${toFinish} more thing${toFinish === 1 ? '' : 's'} on the left and the preview starts.`
                  : 'Fix the YAML and the preview starts.'
              }
              onInvalid={setIssues}
              after={(allOk) =>
                allOk && draft && triggered && !draft.enabled ? (
                  <Button onClick={() => setDraft({ ...draft, enabled: true })}>
                    Turn it on
                  </Button>
                ) : null
              }
            />
            {draft && triggered && (
              <p className="text-xs text-fg-muted">
                {draft.enabled
                  ? 'On: once saved, its triggers start runs.'
                  : 'Off: nothing starts it by itself. Try it, then turn it on.'}
              </p>
            )}
          </div>
        </div>
      )}
    </Page>
  )
}
