import type { ExportDefinition } from '../../api/exportDefinitions'
import type { Schema } from '../../api/schemas'

const field = (name: string, type: string) => ({
  id: name,
  name,
  label: null,
  type,
  required: false,
  restrictions: {},
  default: null,
  position: null,
})

const schema = (
  name: string,
  parent: string | null,
  fields: [string, string][],
): Schema => ({
  id: name,
  name,
  label: null,
  description: null,
  parent_id: parent,
  display_template: null,
  fields: fields.map(([n, t]) => field(n, t)),
  deleted_at: null,
})

// Encounter -> Recording -> Selection: audio on the Recordings, contours and
// tables on the Selections; quality to filter on.
export const ENCOUNTER = schema('encounter', null, [['site', 'string']])
export const RECORDING = schema('recording', 'encounter', [['audio', 'file']])
export const SELECTION = schema('selection', 'recording', [
  ['contour', 'file'],
  ['table', 'file'],
  ['quality', 'string'],
])
export const SCHEMAS = [ENCOUNTER, RECORDING, SELECTION]

export const definition = (
  over: Partial<ExportDefinition> = {},
): ExportDefinition => ({
  id: 'd1',
  schema_id: 'encounter',
  schema_name: 'encounter',
  name: 'Contours',
  holder: 'selection',
  fields: ['contour'],
  filter_tree: null,
  files_layout: 'flat',
  include_files: true,
  tables: [],
  ...over,
})
