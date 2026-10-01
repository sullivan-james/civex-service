import type { ComponentType } from 'react'
import {
  AcceptControl,
  BboxControl,
  BytesControl,
  ChoicesControl,
  DateBoundControl,
  DatetimeBoundControl,
  FilenameTemplateControl,
  GeometryTypesControl,
  NumberControl,
  PrecisionControl,
  SchemaControl,
  TimezoneControl,
  UnitControl,
  type ControlProps,
} from './RestrictionControls'

/** Which editor each descriptor `control` gets. A control the server names
 * that isn't here is shown as "can't be edited here yet" rather than hidden,
 * and the rule's stored value is left untouched. */
export const CONTROLS: Record<string, ComponentType<ControlProps>> = {
  number: NumberControl,
  integer: NumberControl,
  bytes: BytesControl,
  choices: ChoicesControl,
  accept: AcceptControl,
  filename_template: FilenameTemplateControl,
  schema: SchemaControl,
  timezone: TimezoneControl,
  date_bound: DateBoundControl,
  datetime_bound: DatetimeBoundControl,
  unit: UnitControl,
  precision: PrecisionControl,
  geometry_types: GeometryTypesControl,
  bbox: BboxControl,
}
