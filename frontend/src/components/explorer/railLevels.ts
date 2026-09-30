import type { Schema } from '../../api/schemas'
import { isDescendantSchema, schemaLevels } from '../../utils/hierarchy'
import type { RailLevel } from './HierarchyRail'

/** The levels the hierarchy sidebar offers: every schema under `rootSchema`
 * (or from the top when absent) that is at or above the scope -- always, so
 * one click goes back up -- or below it with records in scope. Levels on
 * another branch are left out. `keep` is offered even when empty. */
export function railLevels({
  schemas,
  byId,
  rootSchema,
  scopeSchema,
  counts,
  keep,
}: {
  schemas: Schema[]
  byId: Map<string, Schema>
  rootSchema?: Schema | null
  scopeSchema: Schema | null
  counts: Record<string, number> | undefined
  keep?: string | null
}): RailLevel[] {
  return schemaLevels(schemas, rootSchema ?? undefined).flatMap<RailLevel>(
    ({ schema, depth }) => {
      if (
        scopeSchema &&
        (schema.id === scopeSchema.id ||
          isDescendantSchema(scopeSchema, schema, byId))
      )
        return [{ schema, depth, count: null }]
      if (scopeSchema && !isDescendantSchema(schema, scopeSchema, byId))
        return []
      const count = counts?.[schema.name] ?? 0
      return count > 0 || schema.name === keep ? [{ schema, depth, count }] : []
    },
  )
}
