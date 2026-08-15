import { useMemo } from 'react'
import { Link } from 'react-router'
import { useSchemaLint, useSchemas } from '../../../hooks/useSchemas'
import { errorMessage } from '../../../lib/errors'
import { ErrorState, EmptyState, Table, Thead, Th, Tbody, Tr, Td } from '../../ui'
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
          <StatTile label="Legacy names" value={issues.length} goodDirection="down" />
          <Table>
            <Thead>
              <tr>
                <Th>Kind</Th>
                <Th>Schema</Th>
                <Th>Name</Th>
                <Th>Suggested</Th>
              </tr>
            </Thead>
            <Tbody>
              {issues.map((issue, i) => {
                const schemaId = schemaIdByName.get(issue.schema_name)
                return (
                  <Tr key={`${issue.kind}-${issue.schema_name}-${issue.name}-${i}`}>
                    <Td>{issue.kind}</Td>
                    <Td>
                      {schemaId ? (
                        <Link
                          to={`/schemas/${schemaId}`}
                          className="text-accent hover:underline"
                        >
                          {issue.schema_name}
                        </Link>
                      ) : (
                        issue.schema_name
                      )}
                    </Td>
                    <Td className="font-mono text-xs">{issue.name}</Td>
                    <Td className="font-mono text-xs text-fg-muted">
                      {issue.suggestion ?? '—'}
                    </Td>
                  </Tr>
                )
              })}
            </Tbody>
          </Table>
        </>
      )}
    </WidgetCard>
  )
}
