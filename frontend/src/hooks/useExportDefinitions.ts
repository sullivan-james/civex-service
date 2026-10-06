import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  exportDefinitionsApi,
  type CreateExportDefinition,
  type UpdateExportDefinition,
} from '../api/exportDefinitions'

const DEFINITIONS = ['export-definitions']
const AVAILABLE = ['file-access', 'definitions']

/** The exports saved with one schema. */
export function useExportDefinitions(schema: string | undefined) {
  return useQuery({
    queryKey: [...DEFINITIONS, schema],
    queryFn: () => exportDefinitionsApi.list(schema!),
    enabled: !!schema,
  })
}

/** The exports to offer on a record of a schema, or on a collection. */
export function useAvailableExports(
  where: { schema: string } | { collection: string } | null,
) {
  return useQuery({
    queryKey: [...AVAILABLE, where],
    queryFn: () => exportDefinitionsApi.available(where!),
    enabled: where !== null,
  })
}

/** Every saved export, whatever schema it is saved with. */
export function useAllExports() {
  return useQuery({
    queryKey: [...AVAILABLE, 'all'],
    queryFn: exportDefinitionsApi.all,
  })
}

/** Create an export on a schema, or change one (`name` given). */
export function useSaveExportDefinition(schema: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      name,
      body,
    }: {
      /** The existing export to change; absent to create. */
      name?: string
      body: CreateExportDefinition | UpdateExportDefinition
    }) =>
      name
        ? exportDefinitionsApi.update(
            schema,
            name,
            body as UpdateExportDefinition,
          )
        : exportDefinitionsApi.create(schema, body as CreateExportDefinition),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: DEFINITIONS })
      void qc.invalidateQueries({ queryKey: AVAILABLE })
    },
  })
}

/** Delete an export, from the schema it is saved with (which may be one above
 * the schema whose tab it is shown on). */
export function useDeleteExportDefinition() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ schema, name }: { schema: string; name: string }) =>
      exportDefinitionsApi.delete(schema, name),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: DEFINITIONS })
      void qc.invalidateQueries({ queryKey: AVAILABLE })
    },
  })
}
