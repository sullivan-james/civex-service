import { Select, Input, Button, IconButton } from '../ui'
import { X } from '../ui/icons'
import {
  operatorsFor,
  emptyCondition,
  emptyGroup,
  updateNodeById,
  removeNodeById,
  addChildById,
  type FilterGroupNode,
  type FilterConditionNode,
  type FilterOp,
} from '../../utils/filterTree'
import {
  fieldKey,
  findFilterField,
  type FilterableField,
  type FieldRelation,
} from '../../utils/hierarchy'
import { displayLabel } from '../../utils/naming'
import {
  MultiRecordSearchPicker,
  RecordSearchPicker,
} from '../records/RecordSearchPicker'
import { DynamicField } from '../records/DynamicField'

/** Field types whose record-form input also works as a filter value. The
 * rest (geo, files, tags, ...) are matched as text. */
const TYPED_INPUT = new Set([
  'string',
  'integer',
  'float',
  'enum',
  'date',
  'datetime',
  'url',
])

interface FilterBuilderProps {
  root: FilterGroupNode
  fields: FilterableField[]
  onChange: (root: FilterGroupNode) => void
}

const RELATION_HINT: Record<FieldRelation, string> = {
  self: 'this level',
  ancestor: 'parent record',
  descendant: 'any child record',
}

/** Airtable/Notion-style groupable AND/OR filter builder. Operates on the
 * `FilterTreeNode` shape from utils/filterTree, converted to/from the API's
 * wire format by the caller. A condition may test a field of the listed
 * schema, of an ancestor (its parent record) or of a descendant (matches
 * when any child record does) -- joined columns aren't filterable. */
export function FilterBuilder({ root, fields, onChange }: FilterBuilderProps) {
  return (
    <GroupEditor
      root={root}
      node={root}
      fields={fields}
      onChange={onChange}
      isRoot
    />
  )
}

function FilterValueInput({
  field,
  op,
  value,
  onChange,
}: {
  field: FilterableField | undefined
  op: FilterOp
  value: unknown
  onChange: (value: unknown) => void
}) {
  // A reference is picked by name, not typed as a UUID. Without a target
  // schema there is nothing to search, so it falls through to the text input.
  const targetSchema = field?.restrictions?.schema
  if (
    (field?.type === 'reference' || field?.type === 'reference_list') &&
    typeof targetSchema === 'string' &&
    op !== 'is_null'
  ) {
    if (op === 'in') {
      return (
        <MultiRecordSearchPicker
          schemaName={targetSchema}
          value={Array.isArray(value) ? (value as string[]) : []}
          onChange={onChange}
          aria-label="Value"
          className="w-64"
        />
      )
    }
    return (
      <RecordSearchPicker
        schemaName={targetSchema}
        value={typeof value === 'string' && value ? value : undefined}
        onChange={(id) => onChange(id ?? '')}
        aria-label="Value"
        className="w-56"
      />
    )
  }
  if (op === 'in') {
    const text = Array.isArray(value) ? value.join(', ') : ''
    return (
      <Input
        aria-label="Value (comma-separated)"
        placeholder="value1, value2, …"
        value={text}
        onChange={(e) =>
          onChange(
            e.target.value
              .split(',')
              .map((v) => v.trim())
              .filter(Boolean),
          )
        }
        className="w-48"
      />
    )
  }
  if (field?.type === 'boolean') {
    return (
      <Select
        aria-label="Value"
        value={value === false ? 'false' : 'true'}
        onChange={(e) => onChange(e.target.value === 'true')}
        className="w-28"
      >
        <option value="true">true</option>
        <option value="false">false</option>
      </Select>
    )
  }
  // A substring test is always free text, whatever the field's type.
  if (field && op !== 'contains' && TYPED_INPUT.has(field.type)) {
    const numeric = field.type === 'integer' || field.type === 'float'
    return (
      // The record form's own input for this type -- choices, enums,
      // partial dates, units, timezones -- so a filter can't drift from it.
      <label className="block w-48">
        <span className="sr-only">Value</span>
        <DynamicField
          // Whether a record *needs* the field says nothing about a filter.
          field={{ ...field, required: false }}
          value={value}
          placeholder="Value"
          onChange={(v) =>
            // The server compares by JSON type: "30" would sort as text.
            onChange(numeric && v !== '' && !isNaN(Number(v)) ? Number(v) : v)
          }
        />
      </label>
    )
  }
  return (
    <Input
      aria-label="Value"
      value={String(value ?? '')}
      onChange={(e) => onChange(e.target.value)}
      placeholder="Value"
      className="w-40"
    />
  )
}

function ConditionEditor({
  root,
  node,
  fields,
  onChange,
}: {
  root: FilterGroupNode
  node: FilterConditionNode
  fields: FilterableField[]
  onChange: (root: FilterGroupNode) => void
}) {
  const field = findFilterField(fields, node)

  function update(patch: Partial<FilterConditionNode>) {
    onChange(
      updateNodeById(root, node.id, (n) => ({
        ...(n as FilterConditionNode),
        ...patch,
      })),
    )
  }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <Select
        aria-label="Field"
        value={field ? fieldKey(field) : ''}
        onChange={(e) => {
          const picked = fields.find((f) => fieldKey(f) === e.target.value)
          const ops = operatorsFor(picked?.type)
          update({
            field: picked?.name ?? '',
            schema: picked?.sourceSchemaName,
            value: '',
            // Keep the operator when the new field supports it; otherwise
            // fall back to its first (e.g. reference lists have no "is").
            op: ops.some((o) => o.value === node.op) ? node.op : ops[0].value,
          })
        }}
        className="w-56"
      >
        <option value="">Select field…</option>
        {groupFields(fields).map(({ schemaName, relation, items }) => (
          <optgroup
            key={schemaName}
            label={`${schemaName} (${RELATION_HINT[relation]})`}
          >
            {items.map((f) => (
              <option key={fieldKey(f)} value={fieldKey(f)}>
                {displayLabel(f.name, f.label)}
              </option>
            ))}
          </optgroup>
        ))}
      </Select>
      <Select
        aria-label="Operator"
        value={node.op}
        onChange={(e) => {
          const op = e.target.value as FilterOp
          // "is any of" holds a list, every other operator one id; a value
          // of the wrong shape would render as nothing in the picker.
          const isReference =
            field?.type === 'reference' || field?.type === 'reference_list'
          const reshape =
            isReference && (op === 'in') !== Array.isArray(node.value)
          update(reshape ? { op, value: op === 'in' ? [] : '' } : { op })
        }}
        className="w-32"
      >
        {operatorsFor(field?.type).map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </Select>
      {node.op !== 'is_null' && (
        <FilterValueInput
          field={field}
          op={node.op}
          value={node.value}
          onChange={(value) => update({ value })}
        />
      )}
      <IconButton
        icon={X}
        aria-label="Remove condition"
        variant="subtle"
        size="sm"
        onClick={() => onChange(removeNodeById(root, node.id))}
      />
    </div>
  )
}

/** Fields grouped by owning schema, in the order given (own, ancestors,
 * descendants). */
function groupFields(fields: FilterableField[]) {
  const groups: {
    schemaName: string
    relation: FieldRelation
    items: FilterableField[]
  }[] = []
  for (const f of fields) {
    const last = groups[groups.length - 1]
    if (last && last.schemaName === f.sourceSchemaName) last.items.push(f)
    else
      groups.push({
        schemaName: f.sourceSchemaName,
        relation: f.relation,
        items: [f],
      })
  }
  return groups
}

function GroupEditor({
  root,
  node,
  fields,
  onChange,
  isRoot = false,
}: {
  root: FilterGroupNode
  node: FilterGroupNode
  fields: FilterableField[]
  onChange: (root: FilterGroupNode) => void
  isRoot?: boolean
}) {
  function setOp(op: 'and' | 'or') {
    onChange(
      updateNodeById(root, node.id, (n) => ({ ...(n as FilterGroupNode), op })),
    )
  }

  return (
    <div
      className={
        isRoot ? '' : 'border border-border rounded-md p-2 bg-canvas-subtle'
      }
    >
      <div className="flex items-center gap-2 mb-2">
        <div className="inline-flex rounded-md border border-border overflow-hidden text-xs font-medium">
          <button
            type="button"
            onClick={() => setOp('and')}
            aria-pressed={node.op === 'and'}
            className={`px-2 py-1 cursor-pointer ${node.op === 'and' ? 'bg-accent text-fg-on-emphasis' : 'bg-canvas hover:bg-canvas-inset text-fg-muted'}`}
          >
            AND
          </button>
          <button
            type="button"
            onClick={() => setOp('or')}
            aria-pressed={node.op === 'or'}
            className={`px-2 py-1 cursor-pointer border-l border-border ${node.op === 'or' ? 'bg-accent text-fg-on-emphasis' : 'bg-canvas hover:bg-canvas-inset text-fg-muted'}`}
          >
            OR
          </button>
        </div>
        {node.children.length === 0 && (
          <span className="text-xs text-fg-subtle italic">
            No conditions — matches every record
          </span>
        )}
        {!isRoot && (
          <IconButton
            icon={X}
            aria-label="Remove group"
            variant="subtle"
            size="sm"
            className="ml-auto"
            onClick={() => onChange(removeNodeById(root, node.id))}
          />
        )}
      </div>

      {node.children.length > 0 && (
        <div className="flex flex-col gap-2 mb-2">
          {node.children.map((child) =>
            child.kind === 'group' ? (
              <GroupEditor
                key={child.id}
                root={root}
                node={child}
                fields={fields}
                onChange={onChange}
              />
            ) : (
              <ConditionEditor
                key={child.id}
                root={root}
                node={child}
                fields={fields}
                onChange={onChange}
              />
            ),
          )}
        </div>
      )}

      <div className="flex gap-2">
        <Button
          size="sm"
          onClick={() =>
            onChange(addChildById(root, node.id, emptyCondition()))
          }
        >
          + Condition
        </Button>
        <Button
          size="sm"
          onClick={() => onChange(addChildById(root, node.id, emptyGroup()))}
        >
          + Group
        </Button>
      </div>
    </div>
  )
}
