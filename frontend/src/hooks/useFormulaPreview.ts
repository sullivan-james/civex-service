import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { schemasApi } from '../api/schemas'
import { useDebouncedValue } from './useDebouncedValue'

export interface FormulaPreviewInput {
  expression: string
  result?: string | null
  decimals?: number | null
  /** The formula field being edited, when it exists already. */
  field?: string | null
  /** The record to work it out for; none = the kind's latest. */
  record_id?: string | null
}

/** What a formula would give, asked of the server as the person types (the
 * one implementation of formulas, and the same check saving makes): its
 * value for a record, why it can't be worked out there (`error`), or why it
 * can't be saved (`problem`). Off while the expression is empty. */
export function useFormulaPreview(
  schemaName: string,
  input: FormulaPreviewInput,
) {
  const key = useDebouncedValue(JSON.stringify(input), 300)
  const body = JSON.parse(key) as FormulaPreviewInput
  return useQuery({
    queryKey: ['formula-preview', schemaName, key],
    queryFn: () => schemasApi.previewFormula(schemaName, body),
    enabled: !!schemaName && !!body.expression.trim(),
    placeholderData: keepPreviousData,
    staleTime: 0,
  })
}
