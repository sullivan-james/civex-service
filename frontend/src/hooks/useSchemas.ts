import {
  useQuery,
  useMutation,
  useQueryClient,
  type QueryClient,
  type QueryKey,
} from '@tanstack/react-query'
import { schemasApi, type Schema, type Field } from '../api/schemas'
import { useToast } from '../components/ui/ToastProvider'
import { invalidateRecordNames } from './useRecordName'
import { errorMessage } from '../lib/errors'

/**
 * Applies `updater` to every cached schema (list entries and single-schema
 * queries alike) matching `schemaName`, so a toggle in one view is
 * reflected everywhere without waiting for a round-trip. Returns a snapshot
 * for rollback in onError.
 */
function optimisticUpdateSchema(
  qc: QueryClient,
  schemaName: string,
  updater: (schema: Schema) => Schema,
): Map<QueryKey, unknown> {
  const previous = new Map<QueryKey, unknown>()
  for (const [key, data] of qc.getQueriesData<Schema | Schema[]>({
    queryKey: ['schemas'],
  })) {
    if (!data) continue
    if (Array.isArray(data)) {
      if (!data.some((s) => s.name === schemaName)) continue
      previous.set(key, data)
      qc.setQueryData(
        key,
        data.map((s) => (s.name === schemaName ? updater(s) : s)),
      )
    } else if (data.name === schemaName) {
      previous.set(key, data)
      qc.setQueryData(key, updater(data))
    }
  }
  return previous
}

function rollbackSchemaCache(
  qc: QueryClient,
  previous: Map<QueryKey, unknown> | undefined,
) {
  previous?.forEach((data, key) => qc.setQueryData(key, data))
}

export function useSchemas() {
  return useQuery({ queryKey: ['schemas'], queryFn: schemasApi.list })
}

// Deliberately not under the ['schemas', ...] prefix: optimisticUpdateSchema
// above scans every query cached under that prefix for array entries whose
// `.name` matches a renamed schema, and a NameIssue also carries a `name`
// field -- nesting this here would risk it being mistaken for a Schema and
// overwritten by that logic.
export function useSchemaLint() {
  return useQuery({ queryKey: ['schema-lint'], queryFn: schemasApi.lint })
}

export function useSchema(name: string) {
  return useQuery({
    queryKey: ['schemas', name],
    queryFn: () => schemasApi.get(name),
    enabled: !!name,
  })
}

export function useSchemaDeleteImpact(name: string, enabled: boolean) {
  return useQuery({
    queryKey: ['schemas', name, 'delete-impact'],
    queryFn: () => schemasApi.getDeleteImpact(name),
    enabled: enabled && !!name,
  })
}

export function useCreateSchema() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: schemasApi.create,
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['schemas'] })
      toast.success(`Schema "${created.name}" created`)
    },
  })
}

export function useUpdateSchema(name: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (body: {
      rename?: string
      label?: string
      description?: string
      display_template?: string
    }) => schemasApi.update(name, body),
    onMutate: async (body) => {
      await qc.cancelQueries({ queryKey: ['schemas'] })
      const previous = optimisticUpdateSchema(qc, name, (s) => ({
        ...s,
        ...body,
        // Matches the backend: an empty template clears it.
        display_template:
          body.display_template === undefined
            ? s.display_template
            : body.display_template || null,
      }))
      return { previous }
    },
    onError: (err, _body, context) => {
      rollbackSchemaCache(qc, context?.previous)
      toast.error(
        `Couldn't save changes to schema "${name}" — reverted. ${errorMessage(err)}`,
      )
    },
    onSuccess: (updated) => {
      toast.success(`Schema "${updated.name}" updated`)
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['schemas'] })
      // A new name template or schema name renames every record of it.
      invalidateRecordNames(qc)
    },
  })
}

export function useAddField(schemaName: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (body: {
      name: string
      label?: string
      type: string
      required?: boolean
      restrictions?: Record<string, unknown>
      default?: unknown
    }) => schemasApi.addField(schemaName, body),
    onSuccess: (field) => {
      qc.invalidateQueries({ queryKey: ['schemas'] })
      toast.success(`Field "${field.name}" added`)
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}

export function useUpdateField(schemaName: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: ({
      fieldName,
      ...body
    }: {
      fieldName: string
      rename?: string
      label?: string
      required?: boolean
      restrictions?: Record<string, unknown> | null
    }) => schemasApi.updateField(schemaName, fieldName, body),
    onMutate: async ({ fieldName, ...body }) => {
      await qc.cancelQueries({ queryKey: ['schemas'] })
      const previous = optimisticUpdateSchema(qc, schemaName, (s) => ({
        ...s,
        fields: s.fields.map((f): Field =>
          f.name === fieldName
            ? {
                ...f,
                name: body.rename ?? f.name,
                ...(body.label !== undefined && { label: body.label }),
                ...(body.required !== undefined && {
                  required: body.required,
                }),
                ...(body.restrictions !== undefined && {
                  restrictions: body.restrictions ?? {},
                }),
              }
            : f,
        ),
      }))
      return { previous, fieldName }
    },
    onError: (err, _vars, context) => {
      rollbackSchemaCache(qc, context?.previous)
      toast.error(
        `Couldn't save changes to field "${context?.fieldName}" — reverted. ${errorMessage(err)}`,
      )
    },
    onSuccess: (field) => {
      toast.success(`Field "${field.name}" updated`)
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['schemas'] })
    },
  })
}

export function useDeleteSchema() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (vars: { name: string; undo?: () => Promise<unknown> }) =>
      schemasApi.delete(vars.name),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['schemas'] })
      qc.invalidateQueries({ queryKey: ['schemas-deleted'] })
      toast.success(`Schema "${vars.name}" moved to Recently Deleted`, {
        action: vars.undo
          ? {
              label: 'Undo',
              onClick: () => {
                vars.undo!().then(
                  () => {
                    qc.invalidateQueries({ queryKey: ['schemas'] })
                    qc.invalidateQueries({ queryKey: ['schemas-deleted'] })
                    toast.success(`Schema "${vars.name}" restored`)
                  },
                  (err) => toast.error(errorMessage(err)),
                )
              },
            }
          : undefined,
      })
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}

export function useDeletedSchemas() {
  return useQuery({
    queryKey: ['schemas-deleted'],
    queryFn: schemasApi.listDeleted,
  })
}

export function useRestoreSchema() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: schemasApi.restore,
    onSuccess: (restored) => {
      qc.invalidateQueries({ queryKey: ['schemas'] })
      qc.invalidateQueries({ queryKey: ['schemas-deleted'] })
      toast.success(`Schema "${restored.name}" restored`)
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}

export function usePurgeSchema() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: schemasApi.purge,
    onSuccess: (_data, schemaName) => {
      qc.invalidateQueries({ queryKey: ['schemas'] })
      qc.invalidateQueries({ queryKey: ['schemas-deleted'] })
      toast.success(`Schema "${schemaName}" permanently deleted`)
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}

export function useDeleteField(schemaName: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (fieldName: string) =>
      schemasApi.deleteField(schemaName, fieldName),
    onSuccess: (_data, fieldName) => {
      qc.invalidateQueries({ queryKey: ['schemas'] })
      toast.success(`Field "${fieldName}" deleted`)
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}

export function useReorderFields(schemaName: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (order: string[]) =>
      schemasApi.reorderFields(schemaName, order),
    onMutate: async (order) => {
      await qc.cancelQueries({ queryKey: ['schemas'] })
      const previous = optimisticUpdateSchema(qc, schemaName, (s) => {
        const byId = new Map(s.fields.map((f) => [f.id, f]))
        const reordered = order
          .map((id) => byId.get(id))
          .filter((f): f is Field => !!f)
        // Fields absent from `order` (shouldn't normally happen) are kept,
        // appended at the end, so an optimistic reorder never drops data.
        const remaining = s.fields.filter((f) => !order.includes(f.id))
        return { ...s, fields: [...reordered, ...remaining] }
      })
      return { previous }
    },
    onError: (err, _order, context) => {
      rollbackSchemaCache(qc, context?.previous)
      toast.error(`Couldn't save field order — reverted. ${errorMessage(err)}`)
    },
    onSuccess: () => {
      toast.success('Field order saved')
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['schemas'] })
    },
  })
}
