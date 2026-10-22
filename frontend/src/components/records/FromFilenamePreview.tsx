import type { Field } from '../../api/schemas'
import { useFromFilenamePreview } from '../../hooks/useFromFilenamePreview'
import { firstFilename, fromFilenameRule } from '../../utils/filenameExtract'

/** Under a blank field with a from-filename rule on the new-record form:
 * what the server will fill it with from the file attached so far, so there
 * is nothing to type. Quiet with no file, a typed value, or no rule. */
export function FromFilenamePreview({
  field,
  values,
}: {
  field: Field
  values: Record<string, unknown>
}) {
  const rule = fromFilenameRule(field.restrictions)
  const current = values[field.name]
  const blank = current === undefined || current === null || current === ''
  const filename = rule ? firstFilename(values[rule.field]) : null
  const preview = useFromFilenamePreview(
    filename ?? '',
    rule?.patterns ?? [],
    field.type,
    !!filename && blank,
  )
  if (!rule || !filename || !blank || !preview.data) return null
  const { value, error } = preview.data
  return (
    <p
      role="status"
      className="mt-1 text-xs text-fg-subtle"
      data-testid={`from-filename-${field.name}`}
    >
      {error
        ? `${filename} fits the pattern but ${error}: type a value instead.`
        : value === null
          ? `${filename} doesn't fit the pattern: type a value, or leave it blank.`
          : `Will be filled with ${String(value)} from ${filename}.`}
    </p>
  )
}
