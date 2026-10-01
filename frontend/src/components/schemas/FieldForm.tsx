import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Field as SchemaField, FieldKind, Schema } from '../../api/schemas'
import { errorMessage } from '../../lib/errors'
import { useAddField, useUpdateField } from '../../hooks/useSchemas'
import { useFieldTypes } from '../../hooks/useFieldTypes'
import {
  Button,
  Field,
  FormGrid,
  Input,
  NameLabelFields,
  Checkbox,
  Skeleton,
} from '../ui'
import { nameError } from '../../utils/naming'
import { CONTROLS } from './controlRegistry'
import type { ControlContext, Rules } from './RestrictionControls'

type FieldFormProps = {
  schemaName: string
  schemas: Schema[] | undefined
  /** Names of the schema's fields, offered when building a file name. */
  fieldNames: string[]
  /** Called after a save (with the new field's name when created), or when
   * the person backs out. */
  onDone: (savedName?: string) => void
  /** Told whenever the form differs from what was loaded, so the page can
   * ask before throwing edits away. */
  onDirtyChange?: (dirty: boolean) => void
} & (
  | { mode: 'create'; kind: FieldKind; onChangeKind?: () => void }
  | { mode: 'edit'; field: SchemaField }
)

/** Keep only the rules that say something. */
function tidy(rules: Rules): Rules | undefined {
  const out: Rules = {}
  for (const [k, v] of Object.entries(rules)) {
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v) && v.length === 0) continue
    out[k] = v
  }
  return Object.keys(out).length ? out : undefined
}

/** One field's identity and rules. What can be set comes from the server's
 * field-type descriptors, so a new rule shows up here without a UI change;
 * `CONTROLS` maps each descriptor's `control` to its editor. */
export function FieldForm(props: FieldFormProps) {
  const { mode, schemaName, onDone, onDirtyChange } = props
  const editing = props.mode === 'edit' ? props.field : undefined
  const type = props.mode === 'edit' ? props.field.type : props.kind.type
  const focus = props.mode === 'create' ? props.kind.focus : null

  const descriptors = useFieldTypes()
  const descriptor = descriptors?.types.find((t) => t.type === type)

  const [name, setName] = useState(editing?.name ?? '')
  const [label, setLabel] = useState(editing?.label ?? '')
  const [required, setRequired] = useState(editing?.required ?? false)
  const [defaultVal, setDefaultVal] = useState('')
  const [rules, setRules] = useState<Rules>({
    ...(editing?.restrictions ?? {}),
  })
  const [problems, setProblems] = useState<Record<string, string | null>>({})

  const addField = useAddField(schemaName)
  const updateField = useUpdateField(schemaName)
  const mutation = mode === 'create' ? addField : updateField

  const setRule = useCallback((key: string, value: unknown) => {
    setRules((prev) => {
      const next = { ...prev }
      if (value === undefined) delete next[key]
      else next[key] = value
      return next
    })
  }, [])
  const setProblem = useCallback((key: string, message: string | null) => {
    setProblems((prev) =>
      prev[key] === message ? prev : { ...prev, [key]: message },
    )
  }, [])

  const dirty = useMemo(
    () =>
      mode === 'create'
        ? name !== '' ||
          label !== '' ||
          required ||
          defaultVal !== '' ||
          !!tidy(rules)
        : name !== editing!.name ||
          label !== (editing!.label ?? '') ||
          required !== editing!.required ||
          JSON.stringify(tidy(rules) ?? {}) !==
            JSON.stringify(tidy(editing!.restrictions ?? {}) ?? {}),
    [mode, name, label, required, defaultVal, rules, editing],
  )
  useEffect(() => {
    onDirtyChange?.(dirty)
  }, [dirty, onDirtyChange])

  const problemList = Object.values(problems).filter((p): p is string => !!p)
  const canSubmit =
    !!name.trim() && !nameError(name.trim()) && problemList.length === 0

  const ctx: ControlContext = {
    schemaName,
    fieldNames: props.fieldNames,
    schemas: props.schemas ?? [],
    existing: editing,
  }

  function submit() {
    if (!canSubmit) return
    const built = tidy(rules)
    if (props.mode === 'create') {
      const body: Parameters<typeof addField.mutate>[0] = {
        name: name.trim(),
        type,
        required,
        restrictions: built,
      }
      if (label.trim()) body.label = label.trim()
      if (descriptor?.supports_default !== false && defaultVal !== '')
        body.default = defaultVal
      addField.mutate(body, { onSuccess: (f) => onDone(f.name) })
    } else {
      const trimmedName = name.trim()
      const trimmedLabel = label.trim()
      updateField.mutate(
        {
          fieldName: props.field.name,
          rename: trimmedName !== props.field.name ? trimmedName : undefined,
          // '' clears the label; undefined leaves it untouched.
          label:
            trimmedLabel !== (props.field.label ?? '')
              ? trimmedLabel
              : undefined,
          required,
          restrictions: built ?? {},
        },
        { onSuccess: () => onDone() },
      )
    }
  }

  // The rule the chosen kind leads with comes first.
  const ordered = descriptor
    ? [...descriptor.restrictions].sort(
        (a, b) => Number(b.key === focus) - Number(a.key === focus),
      )
    : []

  return (
    <div className="space-y-6">
      <section aria-label="Identity" className="space-y-3">
        <FormGrid>
          <NameLabelFields
            kind="Field"
            value={{ label, name }}
            onChange={(next) => {
              setLabel(next.label)
              setName(next.name)
            }}
            // An existing name is what workflows reference: never re-derive it.
            deriveName={mode === 'create'}
            onEnter={submit}
            autoFocus
          />
          <Field label="Required" layout="inline" span={4}>
            <Checkbox
              checked={required}
              onChange={(e) => setRequired(e.target.checked)}
            />
          </Field>
          {mode === 'create' && descriptor?.supports_default !== false && (
            <Field label="Default value" span={4}>
              <Input
                size="sm"
                value={defaultVal}
                onChange={(e) => setDefaultVal(e.target.value)}
                placeholder="none"
              />
            </Field>
          )}
        </FormGrid>
        {mode === 'edit' && (
          <p className="text-xs text-fg-subtle">
            The name is what workflows and CSV headers use. Changing it means
            updating any workflow that mentions it.
          </p>
        )}
      </section>

      <section aria-label="What it stores" className="space-y-1">
        <h3 className="text-sm font-semibold text-fg">
          {descriptor?.label ?? type}
          {props.mode === 'create' && props.onChangeKind && (
            <button
              type="button"
              onClick={props.onChangeKind}
              className="ml-3 text-xs font-normal text-accent hover:underline cursor-pointer"
            >
              Change kind
            </button>
          )}
        </h3>
        {descriptor ? (
          <p className="text-sm text-fg-muted">
            {descriptor.description}{' '}
            <span className="text-fg-subtle">
              Stored as: {descriptor.stored_as}.
            </span>
          </p>
        ) : (
          <Skeleton className="h-4 w-64" />
        )}
        {mode === 'edit' && (
          <p className="text-xs text-fg-subtle">
            The type can't change once a field exists.
          </p>
        )}
      </section>

      <section aria-label="Rules" className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-fg">Rules</h3>
          <p className="text-xs text-fg-subtle">
            What this field accepts. Checked when a record is saved; records
            saved earlier are left as they are.
          </p>
        </div>
        {!descriptor && <Skeleton className="h-16 w-full" />}
        {descriptor && ordered.length === 0 && (
          <p className="text-sm text-fg-muted">
            This type has no rules to set.
          </p>
        )}
        {ordered.map((desc) => {
          const Control = CONTROLS[desc.control]
          return Control ? (
            <Control
              key={desc.key}
              desc={desc}
              rules={rules}
              set={setRule}
              problem={setProblem}
              ctx={ctx}
            />
          ) : (
            <p key={desc.key} className="text-xs text-fg-subtle">
              {desc.label} can't be edited here yet.
            </p>
          )
        })}
      </section>

      {(problemList.length > 0 || mutation.error) && (
        <ul role="alert" className="space-y-0.5 text-xs text-danger">
          {problemList.map((p) => (
            <li key={p}>{p}</li>
          ))}
          {mutation.error && <li>{errorMessage(mutation.error)}</li>}
        </ul>
      )}

      <div className="flex items-center gap-2">
        <Button
          variant="primary"
          size="sm"
          onClick={submit}
          disabled={
            mutation.isPending || !canSubmit || (mode === 'edit' && !dirty)
          }
        >
          {mode === 'create'
            ? mutation.isPending
              ? 'Adding…'
              : 'Add field'
            : mutation.isPending
              ? 'Saving…'
              : 'Save changes'}
        </Button>
        <Button size="sm" onClick={() => onDone()}>
          {mode === 'edit' && dirty ? 'Discard changes' : 'Cancel'}
        </Button>
      </div>
    </div>
  )
}
