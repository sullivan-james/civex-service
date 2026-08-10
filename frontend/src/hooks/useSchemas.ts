import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { schemasApi } from '../api/schemas'
import { useToast } from '../components/ui/ToastProvider'
import { errorMessage } from '../lib/errors'

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
      display_fields?: string[] | null
    }) => schemasApi.update(name, body),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ['schemas'] })
      qc.setQueryData(['schemas', updated.name], updated)
      toast.success(`Schema "${updated.name}" updated`)
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
    onSuccess: (field) => {
      qc.invalidateQueries({ queryKey: ['schemas'] })
      toast.success(`Field "${field.name}" updated`)
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}

export function useDeleteSchema() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: schemasApi.delete,
    onSuccess: (_data, schemaName) => {
      qc.invalidateQueries({ queryKey: ['schemas'] })
      qc.invalidateQueries({ queryKey: ['schemas-deleted'] })
      toast.success(`Schema "${schemaName}" moved to Recently Deleted`)
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['schemas'] })
      toast.success('Field order saved')
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}
