/**
 * AND/OR filter tree for the view builder — the frontend half of
 * `civex.domain.filters`. The wire shape (what the API sends/receives) is a
 * plain nested object: `{"field": ..., "op": ..., "value": ...}` for a leaf,
 * `{"and": [...]}`/`{"or": [...]}` for a group. A leaf may name the `schema`
 * whose field it tests -- an ancestor's or descendant's as well as the
 * queried schema's own (see civex/domain/filters.py). `FilterTreeNode` adds a
 * stable `id` and an explicit `kind` discriminant so the builder UI can key
 * and edit individual nodes; `toWireFilterTree`/`fromWireFilterTree` convert
 * between the two.
 */

export type FilterOp =
  'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte' | 'contains' | 'in' | 'is_null'

export const FILTER_OPERATORS: { value: FilterOp; label: string }[] = [
  { value: 'eq', label: 'is' },
  { value: 'ne', label: 'is not' },
  { value: 'gt', label: '>' },
  { value: 'gte', label: '>=' },
  { value: 'lt', label: '<' },
  { value: 'lte', label: '<=' },
  { value: 'contains', label: 'contains' },
  { value: 'in', label: 'is any of' },
  { value: 'is_null', label: 'is empty' },
]

const REFERENCE_OPS: FilterOp[] = ['eq', 'ne', 'in', 'is_null']
const REFERENCE_LIST_OPS: FilterOp[] = ['contains', 'is_null']

/** The operators that mean something for a field of this type. A
 * `reference_list` holds an array, so `eq`/`ne`/`in` compare against the
 * whole array and never behave; only `contains` (a member test) and
 * `is_null` do. A `reference` is one id: no ordering, no substring. */
export function operatorsFor(
  type: string | undefined,
): { value: FilterOp; label: string }[] {
  const allowed =
    type === 'reference'
      ? REFERENCE_OPS
      : type === 'reference_list'
        ? REFERENCE_LIST_OPS
        : null
  if (!allowed) return FILTER_OPERATORS
  return FILTER_OPERATORS.filter((o) => allowed.includes(o.value)).map((o) =>
    type === 'reference_list' && o.value === 'contains'
      ? { ...o, label: 'includes' }
      : o,
  )
}

/** Operators whose value isn't a plain scalar the builder can render as a
 * single text input. */
export const OPERATORS_WITHOUT_VALUE: FilterOp[] = ['is_null']
export const OPERATORS_WITH_LIST_VALUE: FilterOp[] = ['in']

// --- Wire shape (matches civex.domain.filters) ---

export interface FilterConditionWire {
  field: string
  op: FilterOp
  value?: unknown
  /** Schema owning `field`; omitted means the queried schema (or the
   * ancestor owning an inherited name). */
  schema?: string
}

export interface FilterGroupWire {
  and?: FilterTreeWire[]
  or?: FilterTreeWire[]
}

export type FilterTreeWire = FilterConditionWire | FilterGroupWire

// --- Builder-friendly shape ---

export interface FilterConditionNode {
  id: string
  kind: 'condition'
  field: string
  op: FilterOp
  value: unknown
  schema?: string
}

export interface FilterGroupNode {
  id: string
  kind: 'group'
  op: 'and' | 'or'
  children: FilterTreeNode[]
}

export type FilterTreeNode = FilterConditionNode | FilterGroupNode

let nextId = 0

/** Deterministic, not random -- keeps builder state easy to test/reason
 * about (unlike crypto.randomUUID(), this is stable across a test run). */
export function newNodeId(): string {
  nextId += 1
  return `node-${nextId}`
}

export function emptyCondition(): FilterConditionNode {
  return { id: newNodeId(), kind: 'condition', field: '', op: 'eq', value: '' }
}

export function emptyGroup(op: 'and' | 'or' = 'and'): FilterGroupNode {
  return { id: newNodeId(), kind: 'group', op, children: [] }
}

function isGroupWire(wire: FilterTreeWire): wire is FilterGroupWire {
  return 'and' in wire || 'or' in wire
}

export function fromWireFilterTree(wire: FilterTreeWire): FilterTreeNode {
  if (isGroupWire(wire)) {
    const op: 'and' | 'or' = 'and' in wire ? 'and' : 'or'
    const children = (wire.and ?? wire.or ?? []).map(fromWireFilterTree)
    return { id: newNodeId(), kind: 'group', op, children }
  }
  return {
    id: newNodeId(),
    kind: 'condition',
    field: wire.field,
    op: wire.op,
    value: wire.op === 'is_null' ? true : (wire.value ?? ''),
    ...(wire.schema ? { schema: wire.schema } : {}),
  }
}

/** The builder always edits a single root group (even a lone condition gets
 * wrapped in one) so the UI has one consistent shape to render. */
export function wireToRootGroup(wire: FilterTreeWire | null): FilterGroupNode {
  if (!wire) return emptyGroup()
  const node = fromWireFilterTree(wire)
  return node.kind === 'group'
    ? node
    : { id: newNodeId(), kind: 'group', op: 'and', children: [node] }
}

/** Prunes empty groups and conditions with no field selected -- the API
 * rejects an empty group outright, and a still-being-edited condition
 * shouldn't be sent. Returns null when nothing valid remains. */
export function toWireFilterTree(node: FilterTreeNode): FilterTreeWire | null {
  if (node.kind === 'condition') {
    if (!node.field) return null
    const schema = node.schema ? { schema: node.schema } : {}
    if (node.op === 'is_null')
      return { ...schema, field: node.field, op: node.op, value: true }
    return { ...schema, field: node.field, op: node.op, value: node.value }
  }
  const children = node.children
    .map(toWireFilterTree)
    .filter((c): c is FilterTreeWire => c !== null)
  if (children.length === 0) return null
  return node.op === 'and' ? { and: children } : { or: children }
}

// --- Immutable tree edits, by node id (for the builder UI) ---

export function updateNodeById(
  root: FilterGroupNode,
  id: string,
  updater: (node: FilterTreeNode) => FilterTreeNode,
): FilterGroupNode {
  function walk(node: FilterTreeNode): FilterTreeNode {
    if (node.id === id) return updater(node)
    if (node.kind === 'group') {
      return { ...node, children: node.children.map(walk) }
    }
    return node
  }
  return walk(root) as FilterGroupNode
}

export function removeNodeById(
  root: FilterGroupNode,
  id: string,
): FilterGroupNode {
  function walk(node: FilterGroupNode): FilterGroupNode {
    return {
      ...node,
      children: node.children
        .filter((c) => c.id !== id)
        .map((c) => (c.kind === 'group' ? walk(c) : c)),
    }
  }
  return walk(root)
}

export function addChildById(
  root: FilterGroupNode,
  groupId: string,
  child: FilterTreeNode,
): FilterGroupNode {
  function walk(node: FilterGroupNode): FilterGroupNode {
    if (node.id === groupId) {
      return { ...node, children: [...node.children, child] }
    }
    return {
      ...node,
      children: node.children.map((c) => (c.kind === 'group' ? walk(c) : c)),
    }
  }
  return walk(root)
}

/** Every condition in a wire tree, depth-first. */
export function wireConditions(wire: FilterTreeWire): FilterConditionWire[] {
  if (isGroupWire(wire)) {
    return (wire.and ?? wire.or ?? []).flatMap(wireConditions)
  }
  return [wire]
}

/** The tree without the conditions `keep` rejects; groups left empty go too.
 * Null when nothing remains. */
export function pruneWireConditions(
  wire: FilterTreeWire | null,
  keep: (condition: FilterConditionWire) => boolean,
): FilterTreeWire | null {
  if (!wire) return null
  if (isGroupWire(wire)) {
    const op = 'and' in wire ? 'and' : 'or'
    const children = (wire.and ?? wire.or ?? [])
      .map((c) => pruneWireConditions(c, keep))
      .filter((c): c is FilterTreeWire => c !== null)
    return children.length === 0 ? null : { [op]: children }
  }
  return keep(wire) ? wire : null
}
