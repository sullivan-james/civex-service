import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { schemasApi } from '../api/schemas'

export function useSchemas() {
  return useQuery({ queryKey: ['schemas'], queryFn: schemasApi.list })
}

export function useSchema(name: string) {
  return useQuery({
    queryKey: ['schemas', name],
    queryFn: () => schemasApi.get(name),
    enabled: !!name,
  })
}

export function useCreateSchema() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: schemasApi.create,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['schemas'] }),
  })
}

export function useUpdateSchema(name: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      rename?: string
      description?: string
      display_fields?: string[] | null
    }) => schemasApi.update(name, body),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ['schemas'] })
      qc.setQueryData(['schemas', updated.name], updated)
    },
  })
}

export function useAddField(schemaName: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      name: string
      type: string
      required?: boolean
      restrictions?: Record<string, unknown>
      default?: unknown
    }) => schemasApi.addField(schemaName, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['schemas'] }),
  })
}

export function useUpdateField(schemaName: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      fieldName,
      ...body
    }: {
      fieldName: string
      rename?: string
      required?: boolean
      restrictions?: Record<string, unknown> | null
    }) => schemasApi.updateField(schemaName, fieldName, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['schemas'] }),
  })
}

export function useDeleteSchema() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: schemasApi.delete,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['schemas'] }),
  })
}

export function useDeleteField(schemaName: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (fieldName: string) =>
      schemasApi.deleteField(schemaName, fieldName),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['schemas'] }),
  })
}

export function useReorderFields(schemaName: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (order: string[]) =>
      schemasApi.reorderFields(schemaName, order),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['schemas'] }),
  })
}
