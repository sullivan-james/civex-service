import type { Geometry } from '../../utils/geo'
import { Modal, ModalBody, ModalHeader } from '../ui'
import { GeoEditor, type MapSettings } from './GeoEditor'

/** The location editor in a dialog, so the form keeps its compact input and
 * the map gets room. */
export function GeoEditorModal({
  value,
  rules,
  title,
  onApply,
  onClose,
  map,
}: {
  value: Geometry | null
  rules: { geometry_types?: unknown; bbox?: unknown }
  title: string
  onApply: (g: Geometry | null) => void
  onClose: () => void
  map?: MapSettings
}) {
  return (
    <Modal onClose={onClose} size="2xl">
      <ModalHeader onClose={onClose}>{title}</ModalHeader>
      <ModalBody>
        <GeoEditor
          value={value}
          rules={rules}
          onApply={onApply}
          onCancel={onClose}
          map={map}
        />
      </ModalBody>
    </Modal>
  )
}
