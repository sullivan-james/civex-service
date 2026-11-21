import type { Field, Schema } from '../api/schemas'

/** Types a bulk edit can set. A file is added to one record at a time (it is
 * uploaded into that record's collection), so it isn't offered; a formula is
 * worked out, never set. */
const UNEDITABLE = new Set(['file', 'file_list', 'formula'])

/** The fields a bulk edit of `listed` records can change: its own (an
 * inherited field's value is on the record above, so that kind is edited). */
export function bulkEditableFields(listed: Schema): Field[] {
  return listed.fields.filter((f) => !UNEDITABLE.has(f.type))
}
