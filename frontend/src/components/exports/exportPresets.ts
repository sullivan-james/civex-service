import type { ExportDefinition } from '../../api/exportDefinitions'
import type { Schema } from '../../api/schemas'
import { describeDefinition } from '../../utils/exportBuilder'
import type { MenuPreset } from '../files/ExportDialog'

/** A saved export, run in a collection: what the export dialog opens filled in
 * with. The one place that makes it, for every place a saved export is run. */
export function definitionPreset(
  definition: ExportDefinition,
  collection: string,
  schemas?: Schema[],
): MenuPreset {
  const folderName = `${collection}-${definition.name}`
  return {
    label: definition.name,
    hint: describeDefinition(definition, schemas),
    selection: {
      export: `${definition.schema_name}/${definition.name}`,
      collection,
    },
    folderName,
    definition,
  }
}
