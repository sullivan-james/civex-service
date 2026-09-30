import { errorMessage } from '../../lib/errors'
import { fieldErrorInfo } from '../../utils/validationErrors'

export interface FieldSaveError {
  message: string
  technical?: string | null
}

/** A failed save as messages keyed by the field each belongs to: the one the
 * server names, else `fallbackField` (the one just edited, or the row nearest
 * the Add button). */
export function fieldSaveErrors(
  error: unknown,
  fieldNames: string[],
  fallbackField: string | null,
): Record<string, FieldSaveError> {
  const info = fieldErrorInfo(error, fieldNames, errorMessage)
  const out: Record<string, FieldSaveError> = {}
  for (const [name, message] of Object.entries(info.fieldErrors))
    out[name] = { message, technical: info.technical }
  if (info.generalMessage && fallbackField)
    out[fallbackField] = {
      message: info.generalMessage,
      technical: info.technical,
    }
  return out
}
