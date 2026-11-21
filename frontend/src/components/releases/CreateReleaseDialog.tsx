import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useCollections } from '../../hooks/useCollections'
import { useCreateRelease, useReleasePlan } from '../../hooks/useReleases'
import { errorMessage } from '../../lib/errors'
import { pluralise } from '../../lib/utils'
import { formatBytes } from '../../utils/restrictions'
import {
  Button,
  CheckRow,
  Field,
  FormError,
  Input,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  MultiPick,
  SegmentedControl,
  Spinner,
  Textarea,
  useToast,
} from '../ui'

type Covers = 'project' | 'collections'

/** Make a release: what it is called and who made it, what it covers, and
 * whether the files go in, with the server's plan of what it would hold shown
 * before anything is made (the bundle's own plan, asked again as the choices
 * change). */
export function CreateReleaseDialog({ onClose }: { onClose: () => void }) {
  const toast = useToast()
  const navigate = useNavigate()
  const { data: collections = [] } = useCollections()
  const [name, setName] = useState('')
  const [title, setTitle] = useState('')
  const [authors, setAuthors] = useState('')
  const [description, setDescription] = useState('')
  const [licence, setLicence] = useState('')
  const [doi, setDoi] = useState('')
  const [covers, setCovers] = useState<Covers>('project')
  const [chosen, setChosen] = useState<string[]>([])
  const [files, setFiles] = useState(true)
  const create = useCreateRelease()

  const scope = {
    collections: covers === 'collections' ? chosen : null,
    include_files: files,
  }
  const waiting = covers === 'collections' && chosen.length === 0
  const plan = useReleasePlan(scope, !waiting)
  const p = plan.data
  const ready = name.trim() && title.trim() && p && !waiting

  function submit() {
    create.mutate(
      {
        ...scope,
        name: name.trim(),
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
        onSuccess: (made) => {
          toast.success(`Release ${made.name} made`)
          onClose()
          navigate(`/releases/${encodeURIComponent(made.name)}`)
        },
      },
    )
  }

  return (
    <Modal onClose={onClose} size="md">
      <ModalHeader onClose={onClose}>New release</ModalHeader>
      <ModalBody>
        <div className="space-y-3 text-sm">
          <div className="grid grid-cols-2 gap-3">
            <Field
              label="Version"
              required
              info="What people cite, e.g. v1 or 2026-thesis. It can't be changed later."
            >
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="v1"
              />
            </Field>
            <Field
              label="DOI"
              info="If the data has one, e.g. 10.1234/abcd. It can be added later."
            >
              <Input value={doi} onChange={(e) => setDoi(e.target.value)} />
            </Field>
          </div>
          <Field label="Title" required>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field
            label="Authors"
            info="One per line, in the order they are cited."
          >
            <Textarea
              rows={2}
              value={authors}
              onChange={(e) => setAuthors(e.target.value)}
            />
          </Field>
          <Field label="Description">
            <Textarea
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <Field label="Licence" info="e.g. CC-BY-4.0">
            <Input
              value={licence}
              onChange={(e) => setLicence(e.target.value)}
            />
          </Field>
          <div className="flex flex-wrap items-center gap-3">
            <SegmentedControl
              label="What it covers"
              value={covers}
              onChange={setCovers}
              options={[
                { value: 'project', label: 'The whole project' },
                { value: 'collections', label: 'Some collections' },
              ]}
            />
            {covers === 'collections' && (
              <MultiPick
                label="Collections"
                options={collections.map((c) => ({
                  value: c.name,
                  label: c.name,
                }))}
                value={chosen}
                onChange={setChosen}
              />
            )}
          </div>
          <CheckRow
            checked={files}
            onChange={setFiles}
            title="Include the files"
            description={
              p
                ? `${pluralise(p.files, 'stored file')}, ${formatBytes(p.file_bytes)}. Without them the records still name their files.`
                : 'The stored files the records cite.'
            }
          />
          {waiting ? (
            <p className="text-fg-muted">Choose the collections it covers.</p>
          ) : plan.error ? (
            <FormError message={errorMessage(plan.error)} />
          ) : !p ? (
            <p className="flex items-center gap-2 text-fg-muted">
              <Spinner /> Working out what it would hold…
            </p>
          ) : (
            <p className="text-fg-muted" data-testid="release-plan">
              It will hold {pluralise(p.records, 'record')} in{' '}
              {pluralise(p.collections.length, 'collection')},{' '}
              {pluralise(p.schemas, 'schema')}
              {files
                ? `, ${pluralise(p.files, 'file')} (${formatBytes(p.file_bytes)})`
                : ''}
              {p.workflows ? `, ${pluralise(p.workflows, 'workflow')}` : ''}.
              Once made it never changes.
            </p>
          )}
          {p && files && p.files_unreachable > 0 && (
            <p className="text-attention" role="alert">
              {pluralise(p.files_unreachable, 'file')} on a drive that
              can&apos;t be reached now will be left out.
            </p>
          )}
          {create.error && <FormError message={errorMessage(create.error)} />}
        </div>
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="primary"
          disabled={!ready || create.isPending}
          onClick={submit}
        >
          {create.isPending ? 'Making…' : 'Make release'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
