import { useState } from 'react'
import type { PublishResult } from '../../api/remote'
import { useLibraryActions } from '../../hooks/useRemote'
import { errorMessage } from '../../lib/errors'
import {
  Button,
  CheckRow,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
} from '../ui'

/** Publish a workflow from this project to the library, with the plugins its
 * steps use: it is pinned to the versions they become, so publishing a plugin
 * later changes no one who installed this. */
export function PublishDialog({
  stem,
  name,
  sharedVersion,
  onClose,
}: {
  stem: string
  name: string
  /** The newest version in the library, if it is there already. */
  sharedVersion: number | null
  onClose: () => void
}) {
  const { publish } = useLibraryActions()
  const [withPlugins, setWithPlugins] = useState(true)
  const [sent, setSent] = useState<PublishResult | null>(null)

  return (
    <Modal onClose={onClose} size="md">
      <ModalHeader onClose={onClose}>Publish {name}</ModalHeader>
      <ModalBody className="space-y-4 text-sm">
        {!sent && (
          <>
            <p>
              {sharedVersion
                ? `The library has v${sharedVersion}. What is here becomes the next version; computers that installed an earlier one keep it until someone there updates.`
                : 'Others can then install it from the library. It reaches no other computer by itself.'}
            </p>
            <CheckRow
              compact
              title="Send the plugins it uses too"
              description="It is pinned to the versions they become. Without them, it is pinned to the newest the library has."
              checked={withPlugins}
              onChange={setWithPlugins}
            />
          </>
        )}
        {publish.error && (
          <p role="alert" className="text-danger">
            {errorMessage(publish.error)}
          </p>
        )}
        {sent && (
          <div role="status" className="space-y-2">
            <p className="text-success">
              Published{' '}
              {sent.items
                .map((i) => `${i.filename} (v${i.version})`)
                .join(', ')}
              .
            </p>
            {sent.warnings.map((w) => (
              <p key={w} className="text-attention">
                {w}
              </p>
            ))}
          </div>
        )}
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>{sent ? 'Close' : 'Cancel'}</Button>
        {!sent && (
          <Button
            variant="primary"
            disabled={publish.isPending}
            onClick={() =>
              publish.mutate(
                { kind: 'workflow', name: stem, with_plugins: withPlugins },
                { onSuccess: setSent },
              )
            }
          >
            {publish.isPending ? 'Publishing…' : 'Publish'}
          </Button>
        )}
      </ModalFooter>
    </Modal>
  )
}
