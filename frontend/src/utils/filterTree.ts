/**
 * AND/OR filter tree for the view builder — the frontend half of
 * `civex.domain.filters`. The wire shape (what the API sends/receives) is a
 * plain nested object: `{"field": ..., "op": ..., "value": ...}` for a leaf,
 * `{"and": [...]}`/`{"or": [...]}` for a group. `FilterTreeNode` below adds a
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

/** Operators whose value isn't a plain scalar the builder can render as a
 * single text input. */
export const OPERATORS_WITHOUT_VALUE: FilterOp[] = ['is_null']
export const OPERATORS_WITH_LIST_VALUE: FilterOp[] = ['in']

// --- Wire shape (matches civex.domain.filters) ---

export interface FilterConditionWire {
  field: string
  op: FilterOp
  value?: unknown
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
    if (node.op === 'is_null')
      return { field: node.field, op: node.op, value: true }
    return { field: node.field, op: node.op, value: node.value }
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
