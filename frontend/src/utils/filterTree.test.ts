import { describe, it, expect } from 'vitest'
import {
  addChildById,
  emptyCondition,
  emptyGroup,
  removeNodeById,
  toWireFilterTree,
  updateNodeById,
  wireToRootGroup,
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
