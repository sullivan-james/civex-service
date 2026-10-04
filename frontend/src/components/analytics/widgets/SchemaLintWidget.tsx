import { useMemo } from 'react'
import { useSchemaLint, useSchemas } from '../../../hooks/useSchemas'
import { errorMessage } from '../../../lib/errors'
import { ErrorState, EmptyState, DataTable } from '../../ui'
import { StatTile } from '../StatTile'
import { WidgetCard } from '../WidgetCard'

/** Schema/field names that predate slug validation, from
 * `SchemaService.lint_names()` -- a snapshot, not governed by the shared
 * filter bar since naming issues aren't scoped to a date range or dataset.
 * Each row links to its schema for remediation (fields are renamed from
 * the schema detail page; there's no separate per-field route). */
export function SchemaLintWidget() {
  const { data: issues, isLoading, error } = useSchemaLint()
  const { data: schemas } = useSchemas()

  const schemaIdByName = useMemo(() => {
    const map = new Map<string, string>()
    for (const s of schemas ?? []) map.set(s.name, s.id)
    return map
  }, [schemas])

  return (
    <WidgetCard
      title="Naming health"
      description="Schema and field names that predate slug validation"
      viewRunsTo="/schemas"
      viewRunsLabel="View schemas"
    >
      {error ? (
        <ErrorState message={errorMessage(error)} />
      ) : isLoading ? (
        <div className="flex h-[80px] items-center justify-center text-sm text-fg-muted">
          Loading…
        </div>
      ) : !issues || issues.length === 0 ? (
        <EmptyState
          title="All names are valid slugs"
          message="No legacy schema or field names to clean up."
        />
      ) : (
        <>
          <StatTile
            label="Legacy names"
            value={issues.length}
            goodDirection="down"
          />
          <DataTable
            layout="auto"
            columns={[
              { key: 'kind', header: 'Kind', render: (i) => i.kind },
              { key: 'schema', header: 'Schema', render: (i) => i.schema_name },
              {
                key: 'name',
                header: 'Name',
                className: 'font-mono text-xs',
                render: (i) => i.name,
              },
              {
                key: 'suggestion',
                header: 'Suggested',
                className: 'font-mono text-xs text-fg-muted',
                render: (i) => i.suggestion ?? '—',
              },
            ]}
            rows={issues}
            getRowId={(i) => `${i.kind}-${i.schema_name}-${i.name}`}
            rowHref={(i) => {
              const id = schemaIdByName.get(i.schema_name)
              return id ? `/schemas/${id}` : undefined
            }}
          />
        </>
      )}
    </WidgetCard>
  )
}
