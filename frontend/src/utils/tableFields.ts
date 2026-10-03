/** Columns of a flat table (runs, audit entries) described as filterable
 * fields, so the record explorer's filter builder works on them unchanged. */

import type { FilterableField } from './hierarchy'

export interface ColumnSpec {
  name: string
  label: string
  type: 'string' | 'enum' | 'datetime'
  /** For an `enum`: the values the column takes. */
  choices?: string[]
}

export function tableFields(columns: ColumnSpec[]): FilterableField[] {
  return columns.map((c, position) => ({
    id: c.name,
    name: c.name,
    label: c.label,
    type: c.type,
    required: false,
    restrictions: c.choices ? { choices: c.choices } : {},
    default: null,
    position,
    sourceSchemaName: '',
    relation: 'self',
  }))
}
