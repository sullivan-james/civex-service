import { useState } from 'react'
import type { Release, ReleaseAuthor } from '../../api/releases'
import {
  useCorrectRelease,
  useWithdrawRelease,
  useYankPlan,
  useYankRelease,
} from '../../hooks/useReleases'
import { errorMessage } from '../../lib/errors'
import { pluralise } from '../../lib/utils'
import { SPDX_LICENCES } from '../../utils/licences'
import { formatSize } from '../../utils/storage'
import { AuthorsField } from './AuthorsField'
import {
  Checkbox,
  Spinner,
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
  const [authors, setAuthors] = useState<ReleaseAuthor[]>(
    release.authors.length ? release.authors : [{ name: '' }],
  )
  const [keywords, setKeywords] = useState(release.keywords.join(', '))
  const [description, setDescription] = useState(release.description ?? '')
  const [licence, setLicence] = useState(release.licence ?? '')
  const [doi, setDoi] = useState(release.doi ?? '')

  function save() {
    correct.mutate(
      {
        title: title.trim(),
        authors: authors
          .map((a) => ({
            name: a.name.trim(),
            orcid: a.orcid?.trim() || undefined,
            affiliation: a.affiliation?.trim() || undefined,
          }))
          .filter((a) => a.name),
        description: description.trim() || null,
        licence: licence.trim() || null,
        doi: doi.trim() || null,
        keywords: keywords
          .split(',')
          .map((k) => k.trim())
          .filter(Boolean),
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
    <Modal onClose={onClose} size="lg">
      <ModalHeader onClose={onClose}>
        Edit details of {release.name}
      </ModalHeader>
      <ModalBody>
        <div className="space-y-3 text-sm">
          <Field label="Title" required>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <AuthorsField authors={authors} onChange={setAuthors} />
          <Field label="Description">
            <Textarea
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Licence" info="An SPDX id, or any other licence.">
              <Input
                list="release-licences-edit"
                value={licence}
                onChange={(e) => setLicence(e.target.value)}
              />
            </Field>
            <Field label="DOI">
              <Input value={doi} onChange={(e) => setDoi(e.target.value)} />
            </Field>
          </div>
          <datalist id="release-licences-edit">
            {SPDX_LICENCES.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </datalist>
          <Field label="Keywords" info="Separated by commas.">
            <Input
              value={keywords}
              onChange={(e) => setKeywords(e.target.value)}
            />
          </Field>
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
            It keeps its records and files, so work that cited it can still be
            checked; it says it was withdrawn, and why, wherever it is shown. To
            give its data up, yank it instead.
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

/** Yank a release: give its data up for good. Says first, by the clean-up's
 * own count, how many files nothing else uses (a clean-up then removes them)
 * and how many stay for their other users, and asks for a reason and a tick
 * before anything changes. Can't be undone. */
export function YankReleaseDialog({
  release,
  onClose,
}: {
  release: Release
  onClose: () => void
}) {
  const toast = useToast()
  const plan = useYankPlan(release.name)
  const yank = useYankRelease(release.name)
  const [reason, setReason] = useState('')
  const [sure, setSure] = useState(false)
  const p = plan.data
  return (
    <Modal onClose={onClose} size="sm">
      <ModalHeader onClose={onClose}>Yank {release.name}?</ModalHeader>
      <ModalBody>
        <div className="space-y-3 text-sm">
          {plan.error ? (
            <FormError message={errorMessage(plan.error)} />
          ) : !p ? (
            <p className="flex items-center gap-2 text-fg-muted">
              <Spinner /> Counting what it keeps…
            </p>
          ) : (
            <p data-testid="yank-plan">
              It stops keeping its {pluralise(p.files, 'file')} (its records
              included).{' '}
              {p.unused_files > 0
                ? `${pluralise(p.unused_files, 'file')} (${formatSize(p.unused_bytes)}) are used by nothing else, so the next clean-up removes them. `
                : 'Nothing else would be removed. '}
              {p.kept_files > 0
                ? `${pluralise(p.kept_files, 'file')} stay for the records that use them.`
                : ''}
            </p>
          )}
          <p className="text-fg-muted">
            What is left is a record of it (its name, content hash, citation,
            and who yanked it, when and why), so a citation still finds it.
          </p>
          <Field label="Why" required>
            <Textarea
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </Field>
          <Field label="I understand this can't be undone" layout="inline">
            <Checkbox
              checked={sure}
              onChange={(e) => setSure(e.target.checked)}
            />
          </Field>
          {yank.error && <FormError message={errorMessage(yank.error)} />}
        </div>
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="danger"
          disabled={!p || !reason.trim() || !sure || yank.isPending}
          onClick={() =>
            yank.mutate(reason.trim(), {
              onSuccess: () => {
                toast.success(`Release ${release.name} yanked`)
                onClose()
              },
            })
          }
        >
          Yank
        </Button>
      </ModalFooter>
    </Modal>
  )
}
