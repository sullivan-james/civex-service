/**
 * The schema hierarchy (a schema's `parent_id` chain) as the record explorer
 * needs it: which schemas sit above/below the one being browsed, in what
 * order to list them, and which fields a filter may test -- the schema's own
 * fields, an ancestor's (tested on the parent/grandparent record) and a
 * descendant's (matches records having *any* such descendant that satisfies
 * it). Mirrors RecordService._relations on the server.
 */

import type { Schema } from '../api/schemas'
import type { ResolvedField } from './viewFields'

export function schemasById(schemas: Schema[]): Map<string, Schema> {
  return new Map(schemas.map((s) => [s.id, s]))
}

/** Parent, grandparent, … nearest first. */
export function ancestorSchemas(
  schema: Schema,
  byId: Map<string, Schema>,
): Schema[] {
  const chain: Schema[] = []
  let current = schema.parent_id ? byId.get(schema.parent_id) : undefined
  while (current) {
    chain.push(current)
    current = current.parent_id ? byId.get(current.parent_id) : undefined
  }
  return chain
}

export interface SchemaLevel {
  schema: Schema
  /** 0 for a root schema (or for `root` itself, when a root is given). */
  depth: number
}

/** Schemas in hierarchy order (each parent before its children, siblings by
 * name), below `root` if given, else every tree. `root` itself is excluded. */
export function schemaLevels(schemas: Schema[], root?: Schema): SchemaLevel[] {
  const byParent = new Map<string | null, Schema[]>()
  for (const s of schemas) {
    const key = s.parent_id ?? null
    byParent.set(key, [...(byParent.get(key) ?? []), s])
  }
  const out: SchemaLevel[] = []
  const walk = (parentId: string | null, depth: number) => {
    const children = [...(byParent.get(parentId) ?? [])].sort((a, b) =>
      a.name.localeCompare(b.name),
    )
    for (const child of children) {
      out.push({ schema: child, depth })
      walk(child.id, depth + 1)
    }
  }
  walk(root ? root.id : null, 0)
  return out
}

/** True when `candidate` inherits (at any depth) from `ancestor`. */
export function isDescendantSchema(
  candidate: Schema,
  ancestor: Schema,
  byId: Map<string, Schema>,
): boolean {
  return ancestorSchemas(candidate, byId).some((a) => a.id === ancestor.id)
}

export type FieldRelation = 'self' | 'ancestor' | 'descendant'

export interface FilterableField extends ResolvedField {
  /** Where the record that owns this field sits relative to the one listed. */
  relation: FieldRelation
}

/** Stable key for a field within one picker: a name alone is ambiguous
 * across schemas. */
export function fieldKey(f: { sourceSchemaName: string; name: string }) {
  return `${f.sourceSchemaName}::${f.name}`
}

/** Every field a filter on `schema` may test: its own, then each ancestor's
 * (nearest first), then each descendant's. */
export function filterableFields(
  schema: Schema,
  schemas: Schema[],
): FilterableField[] {
  const byId = schemasById(schemas)
  const own = schema.fields.map<FilterableField>((f) => ({
    ...f,
    sourceSchemaName: schema.name,
    relation: 'self',
  }))
  const ancestors = ancestorSchemas(schema, byId).flatMap((a) =>
    a.fields.map<FilterableField>((f) => ({
      ...f,
      sourceSchemaName: a.name,
      relation: 'ancestor',
    })),
  )
  const descendants = schemaLevels(schemas, schema).flatMap(({ schema: d }) =>
    d.fields.map<FilterableField>((f) => ({
      ...f,
      sourceSchemaName: d.name,
      relation: 'descendant',
    })),
  )
  return [...own, ...ancestors, ...descendants]
}

/** Names of the schemas a condition may name when listing `schema`: itself,
 * its ancestors and its descendants. */
export function relatedSchemaNames(
  schema: Schema,
  schemas: Schema[],
): Set<string> {
  const byId = schemasById(schemas)
  return new Set([
    schema.name,
    ...ancestorSchemas(schema, byId).map((a) => a.name),
    ...schemaLevels(schemas, schema).map((l) => l.schema.name),
  ])
}

/** Fields shown as table columns by default: the schema's own, bar files. */
export function defaultColumnNames(schema: Schema): string[] {
  return schema.fields.filter((f) => f.type !== 'file').map((f) => f.name)
}
