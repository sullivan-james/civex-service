import { describe, it, expect } from 'vitest'
import {
  addChildById,
  operatorsFor,
  emptyCondition,
  emptyGroup,
  removeNodeById,
  toWireFilterTree,
  updateNodeById,
  wireToRootGroup,
  pruneWireConditions,
  wireConditions,
  type FilterConditionNode,
  type FilterGroupNode,
} from './filterTree'

describe('toWireFilterTree', () => {
  it('converts a single condition', () => {
    const node: FilterConditionNode = {
      id: 'x',
      kind: 'condition',
      field: 'status',
      op: 'eq',
      value: 'active',
    }
    expect(toWireFilterTree(node)).toEqual({
      field: 'status',
      op: 'eq',
      value: 'active',
    })
  })

  it('forces value to true for is_null', () => {
    const node: FilterConditionNode = {
      id: 'x',
      kind: 'condition',
      field: 'status',
      op: 'is_null',
      value: '',
    }
    expect(toWireFilterTree(node)).toEqual({
      field: 'status',
      op: 'is_null',
      value: true,
    })
  })

  it('drops a condition with no field selected', () => {
    const node: FilterConditionNode = {
      id: 'x',
      kind: 'condition',
      field: '',
      op: 'eq',
      value: 'active',
    }
    expect(toWireFilterTree(node)).toBeNull()
  })

  it('converts a group, pruning empty/invalid children', () => {
    const group: FilterGroupNode = {
      id: 'g',
      kind: 'group',
      op: 'or',
      children: [
        { id: 'a', kind: 'condition', field: 'dept', op: 'eq', value: 'eng' },
        { id: 'b', kind: 'condition', field: '', op: 'eq', value: 'x' },
        { id: 'c', kind: 'group', op: 'and', children: [] },
      ],
    }
    expect(toWireFilterTree(group)).toEqual({
      or: [{ field: 'dept', op: 'eq', value: 'eng' }],
    })
  })

  it('collapses to null when the whole tree is empty', () => {
    expect(toWireFilterTree(emptyGroup())).toBeNull()
  })
})

describe('fromWireFilterTree / wireToRootGroup round trip', () => {
  it('round-trips a nested and/or tree', () => {
    const wire = {
      and: [
        { field: 'dept', op: 'eq' as const, value: 'eng' },
        { or: [{ field: 'age', op: 'gte' as const, value: 30 }] },
      ],
    }
    const root = wireToRootGroup(wire)
    expect(root.kind).toBe('group')
    expect(root.op).toBe('and')
    expect(toWireFilterTree(root)).toEqual(wire)
  })

  it('wraps a bare condition in a synthetic root group', () => {
    const wire = { field: 'age', op: 'gt' as const, value: 18 }
    const root = wireToRootGroup(wire)
    expect(root.kind).toBe('group')
    expect(root.children).toHaveLength(1)
    expect(toWireFilterTree(root)).toEqual({ and: [wire] })
  })

  it('returns an empty root group for a null filter tree', () => {
    const root = wireToRootGroup(null)
    expect(root.children).toEqual([])
    expect(toWireFilterTree(root)).toBeNull()
  })
})

describe('emptyCondition / emptyGroup', () => {
  it('produce distinct ids on each call', () => {
    expect(emptyCondition().id).not.toBe(emptyCondition().id)
    expect(emptyGroup().id).not.toBe(emptyGroup().id)
  })
})

describe('tree edits', () => {
  function makeRoot(): FilterGroupNode {
    return {
      id: 'root',
      kind: 'group',
      op: 'and',
      children: [
        { id: 'c1', kind: 'condition', field: 'dept', op: 'eq', value: 'eng' },
        {
          id: 'g1',
          kind: 'group',
          op: 'or',
          children: [
            { id: 'c2', kind: 'condition', field: 'age', op: 'gt', value: 10 },
          ],
        },
      ],
    }
  }

  it('updateNodeById edits a nested condition without touching siblings', () => {
    const root = makeRoot()
    const updated = updateNodeById(root, 'c2', (n) => ({
      ...(n as FilterConditionNode),
      value: 99,
    }))
    const nestedGroup = updated.children[1] as FilterGroupNode
    expect((nestedGroup.children[0] as FilterConditionNode).value).toBe(99)
    // original untouched (immutable)
    const originalNested = root.children[1] as FilterGroupNode
    expect((originalNested.children[0] as FilterConditionNode).value).toBe(10)
  })

  it('removeNodeById removes a node at any depth', () => {
    const root = makeRoot()
    const updated = removeNodeById(root, 'c2')
    const nestedGroup = updated.children[1] as FilterGroupNode
    expect(nestedGroup.children).toEqual([])
    expect(updated.children).toHaveLength(2)
  })

  it('addChildById appends into the target group only', () => {
    const root = makeRoot()
    const newCondition = emptyCondition()
    const updated = addChildById(root, 'g1', newCondition)
    const nestedGroup = updated.children[1] as FilterGroupNode
    expect(nestedGroup.children).toHaveLength(2)
    expect(nestedGroup.children[1]).toBe(newCondition)
    expect(updated.children[0]).toBe(root.children[0])
  })
})

describe('schema-qualified conditions', () => {
  it('round-trips the schema a condition names', () => {
    const wire = {
      schema: 'selection',
      field: 'selection_table',
      op: 'is_null' as const,
      value: true,
    }
    expect(toWireFilterTree(wireToRootGroup(wire))).toEqual({ and: [wire] })
  })

  it('omits the schema key when there is none', () => {
    const node = wireToRootGroup({ field: 'a', op: 'eq', value: 1 })
    expect(JSON.stringify(toWireFilterTree(node))).not.toContain('schema')
  })
})

describe('wireConditions / pruneWireConditions', () => {
  const tree = {
    and: [
      { field: 'a', op: 'eq' as const, value: 1, schema: 'keep' },
      {
        or: [
          { field: 'b', op: 'eq' as const, value: 2, schema: 'drop' },
          { field: 'c', op: 'eq' as const, value: 3, schema: 'drop' },
        ],
      },
    ],
  }

  it('lists every condition, depth-first', () => {
    expect(wireConditions(tree).map((c) => c.field)).toEqual(['a', 'b', 'c'])
  })

  it('drops rejected conditions and the groups they empty', () => {
    expect(pruneWireConditions(tree, (c) => c.schema === 'keep')).toEqual({
      and: [{ field: 'a', op: 'eq', value: 1, schema: 'keep' }],
    })
  })

  it('is null when nothing is left', () => {
    expect(pruneWireConditions(tree, () => false)).toBeNull()
    expect(pruneWireConditions(null, () => true)).toBeNull()
  })
})

describe('operatorsFor', () => {
  it('keeps every operator for ordinary fields', () => {
    expect(operatorsFor('string').map((o) => o.value)).toContain('gt')
    expect(operatorsFor(undefined)).toHaveLength(9)
  })

  it('offers a reference only the operators that compare one id', () => {
    expect(operatorsFor('reference').map((o) => o.value)).toEqual([
      'eq',
      'ne',
      'in',
      'is_null',
    ])
  })

  it('offers a reference list a member test, not whole-array comparison', () => {
    expect(operatorsFor('reference_list')).toEqual([
      { value: 'contains', label: 'includes' },
      { value: 'is_null', label: 'is empty' },
    ])
  })
})
