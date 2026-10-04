import { Modal, ModalHeader } from '../ui'
import { FolderBrowser } from './FolderBrowser'

/** The folder browser in its own dialog, for choosing a path from a form. */
export function FolderPickerModal({
  initialPath,
  onSelect,
  onClose,
}: {
  initialPath?: string
  onSelect: (path: string) => void
  onClose: () => void
}) {
  return (
    <Modal onClose={onClose} size="xl">
      <ModalHeader onClose={onClose}>Choose a folder</ModalHeader>
      <FolderBrowser
        initialPath={initialPath}
        onCancel={onClose}
        onSelect={(path) => {
          onSelect(path)
          onClose()
        }}
      />
    </Modal>
  )
}
