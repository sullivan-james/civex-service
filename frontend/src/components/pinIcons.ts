import type { ComponentType } from 'react'
import type { PinKind } from '../utils/pins'
import { FileText, Folder, ListFilter, MapPin } from './ui/icons'

type IconType = ComponentType<{
  size?: number
  className?: string
  'aria-hidden'?: boolean | 'true'
}>

export const PIN_ICONS: Record<PinKind, IconType> = {
  view: ListFilter,
  collection: Folder,
  record: FileText,
  place: MapPin,
}
