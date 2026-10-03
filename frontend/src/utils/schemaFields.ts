import type { Schema } from '../api/schemas'
import { displayLabel } from './naming'
import type { TemplateField } from '../components/templates/TemplateBuilder'

/** The schema's own fields followed by inherited ones (a field of the same
 * name closer to the schema hides the inherited one, as on the server). An
 * inherited field says which schema it comes from (`source`); a reference
 * field that names its target schema lists that schema's fields (`reach`), so
 * a name can use `{site.code}`. Reached fields don't reach further: it is one
 * hop on the server too. */
export function fieldsWithInherited(
  schema: Schema,
  allSchemas: Schema[] | undefined,
  withReach = true,
): TemplateField[] {
  const out: TemplateField[] = []
  const seen = new Set<string>()
  let current: Schema | undefined = schema
  while (current && !seen.has(`schema:${current.id}`)) {
    seen.add(`schema:${current.id}`)
    const source =
      current === schema ? null : displayLabel(current.name, current.label)
    for (const f of current.fields) {
      if (seen.has(f.name)) continue
      seen.add(f.name)
      const target =
        withReach && f.type === 'reference'
          ? allSchemas?.find((s) => s.name === f.restrictions?.schema)
          : undefined
      out.push({
        name: f.name,
        label: displayLabel(f.name, f.label),
        dtype: f.type,
        source,
        reach: target
          ? fieldsWithInherited(target, allSchemas, false)
          : undefined,
      })
    }
    const parentId: string | null = current.parent_id
    current = parentId ? allSchemas?.find((s) => s.id === parentId) : undefined
  }
  return out
}
