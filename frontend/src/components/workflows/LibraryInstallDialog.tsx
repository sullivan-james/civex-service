import { useState } from 'react'
import type { InstallPlan, LibraryHere } from '../../api/remote'
import {
  useInstallPlan,
  useLibraryActions,
  useLibraryItem,
} from '../../hooks/useRemote'
import { errorMessage } from '../../lib/errors'
import {
  Button,
  CheckRow,
  Disclosure,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
} from '../ui'

function stateOf(here: LibraryHere, had: number | null, to: number): string {
  if (here === 'same') return 'Unchanged'
  if (had) return had > to ? `Back from v${had}` : `Update from v${had}`
  if (here === 'different') return 'Replaces yours'
  return 'New'
}

/** Install a version of a library item (a workflow brings the plugin versions
 * it was published with). Shows what it writes, which of it is code, what
 * starts it by itself and what it would break here, before anything is
 * written. Plugin code needs an explicit "I trust it"; breaking workflows here
 * needs an explicit "install anyway". */
export function LibraryInstallDialog({
  kind,
  name,
  version = null,
  onClose,
}: {
  kind: 'workflow' | 'plugin'
  name: string
  /** Which version; the newest when null. */
  version?: number | null
  onClose: () => void
}) {
  const [replace, setReplace] = useState(false)
  const [force, setForce] = useState(false)
  const [trusted, setTrusted] = useState(false)
  const options = { version, replace, force }
  const { data: plan, error } = useInstallPlan({ kind, name }, options)
  const { install } = useLibraryActions()
  const [done, setDone] = useState<InstallPlan | null>(null)
  const changedHere = plan?.steps.some(
    (s) => s.here === 'different' && !s.local_version,
  )
  const top = plan?.steps[plan.steps.length - 1]
  const title = `${version ? 'Install' : 'Install the newest'} ${
    top?.item.filename ?? name
  }${top ? ` (v${top.item.version})` : ''}`

  return (
    <Modal onClose={onClose} size="xl">
      <ModalHeader onClose={onClose}>{title}</ModalHeader>
      <ModalBody className="space-y-4 text-sm">
        {error && (
          <p role="alert" className="text-danger">
            {errorMessage(error)}
          </p>
        )}
        {!plan && !error && <p className="text-fg-muted">Checking…</p>}
        {plan && (
          <>
            <ul className="space-y-2">
              {plan.steps.map((s) => (
                <li key={s.path} className="rounded border border-border p-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-mono">{s.path}</span>
                    <span className="text-xs text-fg-muted">
                      {stateOf(s.here, s.local_version, s.item.version)} · v
                      {s.item.version}
                      {s.item.published_by
                        ? ` by ${s.item.published_by}`
                        : ''}{' '}
                      ·{' '}
                      <span className="font-mono">
                        {s.item.sha256.slice(0, 12)}
                      </span>
                    </span>
                  </div>
                  {s.item.kind === 'plugin' && s.here !== 'same' && (
                    <Disclosure summary="Read the code">
                      <PluginCode name={s.item.name} version={s.item.version} />
                    </Disclosure>
                  )}
                </li>
              ))}
            </ul>
            {plan.warnings.length > 0 && (
              <ul className="space-y-1 text-attention">
                {plan.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
            {plan.breaks.length > 0 && (
              <div className="space-y-2 rounded-md border border-danger-subtle-border bg-danger-subtle p-3 text-danger">
                <p>It would break these workflows here:</p>
                <ul className="list-disc space-y-1 pl-5">
                  {plan.breaks.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
                <CheckRow
                  compact
                  title="Install anyway: they won't run until they're fixed"
                  checked={force}
                  onChange={setForce}
                />
              </div>
            )}
            {plan.blocked.length > 0 && (
              <ul role="alert" className="space-y-1 text-danger">
                {plan.blocked.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            )}
            {changedHere && (
              <CheckRow
                compact
                title="Replace the files that were changed here"
                checked={replace}
                onChange={setReplace}
              />
            )}
            {plan.runs_code && (
              <div className="space-y-2 rounded-md border border-danger-subtle-border bg-danger-subtle p-3 text-danger">
                <p>
                  This installs plugin code. It will run on this computer with
                  your permissions, whenever a workflow uses it.
                </p>
                <CheckRow
                  compact
                  title="I've read it and trust whoever published it"
                  checked={trusted}
                  onChange={setTrusted}
                />
              </div>
            )}
            {done && (
              <p role="status" className="text-success">
                Installed.
              </p>
            )}
            {install.error && (
              <p role="alert" className="text-danger">
                {errorMessage(install.error)}
              </p>
            )}
          </>
        )}
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>{done ? 'Close' : 'Cancel'}</Button>
        {!done && (
          <Button
            variant="primary"
            disabled={
              !plan ||
              plan.blocked.length > 0 ||
              plan.steps.every((s) => s.here === 'same') ||
              (plan.runs_code && !trusted) ||
              install.isPending
            }
            onClick={() =>
              install.mutate(
                { kind, name, version, replace, force },
                { onSuccess: setDone },
              )
            }
          >
            {install.isPending ? 'Installing…' : 'Install'}
          </Button>
        )}
      </ModalFooter>
    </Modal>
  )
}

function PluginCode({ name, version }: { name: string; version: number }) {
  const { data, error } = useLibraryItem('plugin', name, version)
  if (error) return <p className="text-danger">{errorMessage(error)}</p>
  if (!data) return <p className="text-fg-muted">Loading…</p>
  return (
    <pre className="mt-2 max-h-80 overflow-auto rounded bg-canvas-inset p-2 font-mono text-xs">
      {data.content}
    </pre>
  )
}
