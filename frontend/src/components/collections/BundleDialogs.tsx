import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { bundleApi, type BundleImportResult } from '../../api/bundle'
import { errorMessage } from '../../lib/errors'
import { pluralise } from '../../lib/utils'
import { formatBytes } from '../../utils/restrictions'
import {
  Button,
  CheckRow,
  FormError,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Spinner,
} from '../ui'

/** Export the project as a bundle: one file another civex can read. Shows
 * what would go in (the server's plan, asked again as the choice changes) and
 * whether to carry the stored files, then starts the download. */
export function ExportBundleDialog({ onClose }: { onClose: () => void }) {
  const [files, setFiles] = useState(true)
  const plan = useQuery({
    queryKey: ['bundle-plan', files],
    queryFn: () => bundleApi.plan({ files }),
  })
  const p = plan.data

  return (
    <Modal onClose={onClose} size="sm">
      <ModalHeader onClose={onClose}>Export a bundle</ModalHeader>
      <ModalBody>
        <div className="space-y-3 text-sm">
          <p className="text-fg-muted">
            One file another civex can read into a project: every schema, every
            collection and its records (their ids kept), and the project&apos;s
            workflows and plugins.
          </p>
          {plan.error ? (
            <FormError message={errorMessage(plan.error)} />
          ) : !p ? (
            <p className="flex items-center gap-2 text-fg-muted">
              <Spinner /> Working out what would go in…
            </p>
          ) : (
            <dl className="space-y-1" data-testid="bundle-plan">
              <Row label="Schemas" value={p.schemas} />
              <Row label="Collections" value={p.collections.length} />
              <Row label="Records" value={p.records} />
              <Row label="Workflows" value={p.workflows} />
              <Row label="Plugins" value={p.plugins} />
            </dl>
          )}
          <CheckRow
            checked={files}
            onChange={setFiles}
            title="Include the files"
            description={
              p
                ? `${pluralise(p.files, 'stored file')}, ${formatBytes(p.file_bytes)}. Without them the records still name their files, and the files can be sent later.`
                : 'The stored files the records cite.'
            }
          />
          {p && files && p.files_unreachable > 0 && (
            <p className="text-attention" role="alert">
              {pluralise(p.files_unreachable, 'file')} on a drive that
              can&apos;t be reached now will be left out.
            </p>
          )}
        </div>
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="primary"
          disabled={!p}
          onClick={() => {
            bundleApi.download({ files })
            onClose()
          }}
        >
          Download
        </Button>
      </ModalFooter>
    </Modal>
  )
}

function Row({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-fg-muted">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  )
}

/** What an import did, in the words the server used. */
export function BundleImportResultModal({
  result,
  onClose,
}: {
  result: BundleImportResult
  onClose: () => void
}) {
  const and = (n: number, what: string) => (n ? `, ${n} ${what}` : '')
  return (
    <Modal onClose={onClose} size="sm">
      <ModalHeader onClose={onClose}>Import complete</ModalHeader>
      <ModalBody>
        <dl className="text-sm space-y-1">
          <Row
            label="Schemas"
            value={`${result.schemas_new} new${and(result.schemas_existing.length, 'already here')}`}
          />
          <Row
            label="Collections"
            value={`${result.collections_new} new${and(result.collections_existing.length, 'already here')}`}
          />
          <Row
            label="Records"
            value={`${result.records_added} added${and(result.records_existing, 'already here')}${and(result.records_skipped, 'skipped')}`}
          />
          <Row
            label="Files"
            value={`${result.files_added} added${and(result.files_missing, 'not in the bundle or here')}${and(result.files_refused, 'refused')}`}
          />
          <Row label="Workflows" value={result.workflows} />
          <Row label="Plugins" value={result.plugins} />
        </dl>
        {result.skipped.length > 0 && (
          <ul className="mt-3 text-sm text-attention space-y-1" role="alert">
            {result.skipped.slice(0, 10).map((s) => (
              <li key={s.id}>
                Record {s.id.slice(0, 8)}: {s.reason}
              </li>
            ))}
            {result.records_skipped > 10 && (
              <li>…and {result.records_skipped - 10} more.</li>
            )}
          </ul>
        )}
        {result.members_skipped.length > 0 && (
          <ul className="mt-3 text-sm text-attention space-y-1">
            {result.members_skipped.map((s) => (
              <li key={s.id}>
                {s.id}: {s.reason}
              </li>
            ))}
          </ul>
        )}
        {result.plugins > 0 && (
          <p className="mt-3 text-sm text-attention">
            Plugins are code. Read what was added to the project&apos;s plugins
            before running workflows.
          </p>
        )}
      </ModalBody>
      <ModalFooter>
        <Button variant="primary" onClick={onClose}>
          Done
        </Button>
      </ModalFooter>
    </Modal>
  )
}
