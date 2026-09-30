import { useMemo, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import type { Schema } from '../../api/schemas'
import { useRecord, useRecordCounts } from '../../hooks/useRecords'
import { useSchemas } from '../../hooks/useSchemas'
import {
  applyExplorerPatch,
  parseExplorerState,
} from '../../utils/explorerState'
import { ancestorSchemas, schemasById } from '../../utils/hierarchy'
import { HierarchyRail } from './HierarchyRail'
import { railLevels } from './railLevels'

const NO_SCHEMAS: Schema[] = []

/** The schema hierarchy of a collection, beside whatever is being looked at:
 * the collection's record list (scoped by the URL's `within`) or a single
 * record (`recordId`). Levels at or above that scope are always there, the
 * ones below show how many records they hold in it. Picking one lists that
 * schema in the collection. */
export function HierarchySidebar({
  dataset,
  collectionId,
  recordId,
}: {
  /** Collection name, for the record counts. */
  dataset: string
  /** Collection id, for the link back to its list. */
  collectionId: string
  /** Set on a record page: that record is the scope. */
  recordId?: string
}) {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const state = useMemo(() => parseExplorerState(searchParams), [searchParams])
  const { data: schemaList } = useSchemas()
  const schemas = schemaList ?? NO_SCHEMAS
  const byId = useMemo(() => schemasById(schemas), [schemas])
  const byName = useMemo(
    () => new Map(schemas.map((s) => [s.name, s])),
    [schemas],
  )

  const rootId = recordId ?? state.within ?? null
  const { data: scopeRecord } = useRecord(rootId)
  const scopeSchema = scopeRecord
    ? (byName.get(scopeRecord.schema_name) ?? null)
    : null
  const { data: counts } = useRecordCounts(
    dataset,
    rootId ? { within: rootId } : undefined,
  )
  const levels = useMemo(
    () =>
      railLevels({
        schemas,
        byId,
        scopeSchema,
        counts,
        keep: recordId ? null : state.schema,
      }),
    [schemas, byId, scopeSchema, counts, recordId, state.schema],
  )

  // On a record page the record's own level is the current one; in a list,
  // the schema being listed (the top level until one is chosen).
  const current = recordId
    ? (scopeRecord?.schema_name ?? null)
    : state.schema && levels.some((l) => l.schema.name === state.schema)
      ? state.schema
      : (levels[0]?.schema.name ?? null)

  function pick(target: Schema) {
    // Stay inside the nearest record above the target's level.
    const above = new Set(ancestorSchemas(target, byId).map((s) => s.id))
    const chain = scopeRecord
      ? [...(scopeRecord.ancestors ?? []), scopeRecord]
      : []
    const holder = [...chain]
      .reverse()
      .find((r) => above.has(byName.get(r.schema_name)?.id ?? ''))
    const patch = { schema: target.name, within: holder?.id ?? null, q: '' }
    if (recordId)
      navigate(
        `/collections/${collectionId}?${applyExplorerPatch(new URLSearchParams(), patch)}`,
      )
    else setSearchParams((prev) => applyExplorerPatch(prev, patch))
  }

  if (levels.length === 0) return null
  return <HierarchyRail levels={levels} current={current} onPick={pick} />
}

/** Page content with the collection's hierarchy kept beside it. */
export function WithHierarchy({
  dataset,
  collectionId,
  recordId,
  children,
}: {
  dataset: string | undefined
  collectionId: string | undefined
  recordId?: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-col gap-4 md:flex-row md:items-start">
      {dataset && collectionId && (
        <HierarchySidebar
          dataset={dataset}
          collectionId={collectionId}
          recordId={recordId}
        />
      )}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}
