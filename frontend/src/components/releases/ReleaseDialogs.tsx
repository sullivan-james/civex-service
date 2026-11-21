import { useState } from 'react'
import type { Release } from '../../api/releases'
import { useCorrectRelease, useWithdrawRelease } from '../../hooks/useReleases'
import { errorMessage } from '../../lib/errors'
import {
  Button,
  Field,
  FormError,
  Input,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Textarea,
  useToast,
} from '../ui'

/** Correct a release's citation details. Its content never changes; what it
 * said before stays in its history. */
export function EditReleaseDialog({
  release,
  onClose,
}: {
  release: Release
  onClose: () => void
}) {
  const toast = useToast()
  const correct = useCorrectRelease(release.name)
  const [title, setTitle] = useState(release.title)
  const [authors, setAuthors] = useState(release.authors.join('\n'))
  const [description, setDescription] = useState(release.description ?? '')
  const [licence, setLicence] = useState(release.licence ?? '')
  const [doi, setDoi] = useState(release.doi ?? '')

  function save() {
    correct.mutate(
      {
        title: title.trim(),
        authors: authors
          .split('\n')
          .map((a) => a.trim())
          .filter(Boolean),
        description: description.trim() || null,
        licence: licence.trim() || null,
        doi: doi.trim() || null,
      },
      {
        onSuccess: () => {
          toast.success('Details corrected')
          onClose()
        },
      },
    )
  }

  return (
    <Modal onClose={onClose} size="md">
      <ModalHeader onClose={onClose}>
        Edit details of {release.name}
      </ModalHeader>
      <ModalBody>
        <div className="space-y-3 text-sm">
          <Field label="Title" required>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field
            label="Authors"
            info="One per line, in the order they are cited."
          >
            <Textarea
              rows={3}
              value={authors}
              onChange={(e) => setAuthors(e.target.value)}
            />
          </Field>
          <Field label="Description">
            <Textarea
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Licence">
              <Input
                value={licence}
                onChange={(e) => setLicence(e.target.value)}
              />
            </Field>
            <Field label="DOI">
              <Input value={doi} onChange={(e) => setDoi(e.target.value)} />
            </Field>
          </div>
          {correct.error && <FormError message={errorMessage(correct.error)} />}
        </div>
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="primary"
          disabled={!title.trim() || correct.isPending}
          onClick={save}
        >
          Save
        </Button>
      </ModalFooter>
    </Modal>
  )
}

/** Withdraw a release, saying why. It and its bundle are kept. */
export function WithdrawReleaseDialog({
  release,
  onClose,
}: {
  release: Release
  onClose: () => void
}) {
  const toast = useToast()
  const withdraw = useWithdrawRelease(release.name)
  const [reason, setReason] = useState('')
  return (
    <Modal onClose={onClose} size="sm">
      <ModalHeader onClose={onClose}>Withdraw {release.name}?</ModalHeader>
      <ModalBody>
        <div className="space-y-3 text-sm">
          <p className="text-fg-muted">
            It is kept, with its bundle, so work that cited it can still be
            checked; it says it was withdrawn, and why, wherever it is shown.
          </p>
          <Field label="Why" required>
            <Textarea
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </Field>
          {withdraw.error && (
            <FormError message={errorMessage(withdraw.error)} />
          )}
        </div>
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="danger"
          disabled={!reason.trim() || withdraw.isPending}
          onClick={() =>
            withdraw.mutate(reason.trim(), {
              onSuccess: () => {
                toast.success(`Release ${release.name} withdrawn`)
                onClose()
              },
            })
          }
        >
          Withdraw
        </Button>
      </ModalFooter>
    </Modal>
  )
}
