/**
 * Field resolution for the view builder's column picker — the frontend
 * half of `SchemaService.collect_fields` (own fields first, then the
 * parent chain, own shadows inherited) plus the single-hop reference-field
 * join enumeration that `ViewService._validate_join_column` accepts.
 */

import type { Field, Schema } from '../api/schemas'

export interface ResolvedField extends Field {
  /** Schema the field is actually defined on -- itself, or an ancestor. */
  sourceSchemaName: string
}

/** Own fields, then each ancestor's own fields (nearest first), skipping
 * any name already seen closer to the leaf. */
export function collectFields(
  schema: Schema,
  schemasById: Map<string, Schema>,
): ResolvedField[] {
  const seen = new Set<string>()
  const resolved: ResolvedField[] = []

  let current: Schema | undefined = schema
  while (current) {
    for (const field of current.fields) {
      if (seen.has(field.name)) continue
      seen.add(field.name)
      resolved.push({ ...field, sourceSchemaName: current.name })
    }
    current = current.parent_id ? schemasById.get(current.parent_id) : undefined
  }
  return resolved
}

export interface JoinableColumn {
  /** "ref_field.target_field" -- the column key the view/preview API expects. */
  value: string
  /** Human-facing label, e.g. "Customer -> Email". */
  label: string
  refField: ResolvedField
  targetField: ResolvedField
}

/** Every "ref_field.target_field" column reachable by one hop through a
 * `reference` field on `schema` -- mirrors the join columns
 * `ViewService._validate_join_column` accepts, computed client-side from
 * the already-fetched schema list so the picker doesn't need extra calls. */
export function joinableColumns(
  schema: Schema,
  schemasById: Map<string, Schema>,
  schemasByName: Map<string, Schema>,
): JoinableColumn[] {
  const columns: JoinableColumn[] = []
  for (const field of collectFields(schema, schemasById)) {
    if (field.type !== 'reference') continue
    const targetSchemaName = field.restrictions?.schema
    if (typeof targetSchemaName !== 'string') continue
    const targetSchema = schemasByName.get(targetSchemaName)
    if (!targetSchema) continue
    for (const targetField of collectFields(targetSchema, schemasById)) {
      columns.push({
        value: `${field.name}.${targetField.name}`,
        label: `${field.label ?? field.name} → ${targetField.label ?? targetField.name}`,
        refField: field,
        targetField,
      })
    }
  }
  return columns
}
