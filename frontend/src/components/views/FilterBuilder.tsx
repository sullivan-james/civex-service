import { Select, Input, Button, IconButton } from '../ui'
import { X } from '../ui/icons'
import {
  FILTER_OPERATORS,
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
  type FilterableField,
  type FieldRelation,
} from '../../utils/hierarchy'
import { displayLabel } from '../../utils/naming'
import {
  effectiveTimeZone,
  utcToZonedLocal,
  zonedLocalToUTC,
} from '../../utils/dates'

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

/** The field a condition names. A condition without a schema (saved before
 * conditions could name one) means the listed schema's, or an ancestor's. */
function fieldOf(
  fields: FilterableField[],
  node: FilterConditionNode,
): FilterableField | undefined {
  return fields.find(
    (f) =>
      f.name === node.field &&
      (node.schema
        ? f.sourceSchemaName === node.schema
        : f.relation !== 'descendant'),
  )
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
  const choices = field?.restrictions?.choices
  if (Array.isArray(choices)) {
    return (
      <Select
        aria-label="Value"
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
        className="w-40"
      >
        <option value="">Select…</option>
        {choices.map((c) => (
          <option key={String(c)} value={String(c)}>
            {String(c)}
          </option>
        ))}
      </Select>
    )
  }
  if (field?.type === 'date') {
    return (
      <Input
        aria-label="Value"
        type="date"
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
        className="w-40"
      />
    )
  }
  if (field?.type === 'datetime') {
    // A view belongs to a schema, not a collection, so only the field's own
    // timezone override is known here; otherwise it's the viewer's zone.
    const timeZone = effectiveTimeZone(field, null)
    return (
      <Input
        aria-label="Value"
        type="datetime-local"
        value={utcToZonedLocal(String(value ?? ''), timeZone)}
        onChange={(e) => {
          // A wall time in a DST gap/overlap resolves to no single instant;
          // keep the previous filter value rather than store a guess.
          const utc = zonedLocalToUTC(e.target.value, timeZone)
          if (utc !== null) onChange(utc)
        }}
        className="w-56"
      />
    )
  }
  if (field?.type === 'integer' || field?.type === 'float') {
    return (
      <Input
        aria-label="Value"
        type="number"
        value={value === '' || value == null ? '' : String(value)}
        onChange={(e) =>
          onChange(e.target.value === '' ? '' : Number(e.target.value))
        }
        className="w-32"
      />
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
  const field = fieldOf(fields, node)

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
          update({
            field: picked?.name ?? '',
            schema: picked?.sourceSchemaName,
            value: '',
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
        onChange={(e) => update({ op: e.target.value as FilterOp })}
        className="w-32"
      >
        {FILTER_OPERATORS.map((o) => (
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
