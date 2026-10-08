import { useState } from 'react'
import type { InstallPlan, LibraryItem } from '../../api/remote'
import {
  useInstallPlan,
  useLibrary,
  useLibraryActions,
  useLibraryItem,
  useRemoteStatus,
} from '../../hooks/useRemote'
import { usePlugins } from '../../hooks/usePlugins'
import { useWorkflows } from '../../hooks/useWorkflows'
import { errorMessage } from '../../lib/errors'
import {
  Badge,
  Button,
  CheckRow,
  ConfirmDialog,
  DataTable,
  Disclosure,
  EmptyState,
  Field,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Select,
  type DataTableColumn,
} from '../ui'

const HERE: Record<
  string,
  { label: string; variant: 'default' | 'success' | 'attention' }
> = {
  absent: { label: 'Not here', variant: 'default' },
  same: { label: 'Installed', variant: 'success' },
  different: { label: 'Differs here', variant: 'attention' },
}

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString() : ''
}

const COLUMNS: DataTableColumn<LibraryItem>[] = [
  {
    key: 'name',
    header: 'Name',
    render: (i) => (
      <span className="flex flex-col">
        <span className="font-medium text-fg">
          {i.title ?? i.name}{' '}
          <span className="text-xs text-fg-muted">
            {i.kind === 'plugin' ? 'plugin' : 'workflow'}
          </span>
        </span>
        <span className="font-mono text-xs text-fg-muted">{i.filename}</span>
      </span>
    ),
  },
  {
    key: 'published',
    header: 'Published',
    render: (i) => (
      <span className="text-sm">
        v{i.version}
        {i.published_by ? ` by ${i.published_by}` : ''}
        <span className="block text-xs text-fg-muted">
          {when(i.published_at)}
        </span>
      </span>
    ),
  },
  {
    key: 'here',
    header: 'Here',
    render: (i) =>
      i.here ? (
        <Badge variant={HERE[i.here].variant}>{HERE[i.here].label}</Badge>
      ) : null,
  },
  {
    key: 'notes',
    header: 'Notes',
    render: (i) => (
      <span className="text-xs text-fg-muted">
        {i.provides && <span className="block">Provides {i.provides}</span>}
        {i.triggers.map((t) => (
          <span key={t} className="block">
            Runs by itself: {t}
          </span>
        ))}
        {i.needs.length > 0 && (
          <span className="block">Uses {i.needs.join(', ')}</span>
        )}
        {i.missing.length > 0 && (
          <span className="block text-danger">
            Needs {i.missing.join(', ')}, which is nowhere
          </span>
        )}
      </span>
    ),
  },
]

/** Workflows and plugins shared through the authority's library: published
 * from one computer, installed by a person on another. Nothing arrives here by
 * itself. The same as `civex sync library`, through the same calls. */
export function LibraryPanel() {
  const { data: status } = useRemoteStatus()
  const sharing = !!status && (status.serving || !!status.remote)
  const { data: items, isLoading, error } = useLibrary(sharing)
  const { unpublish } = useLibraryActions()
  const [installing, setInstalling] = useState<LibraryItem | null>(null)
  const [publishing, setPublishing] = useState(false)
  const [removing, setRemoving] = useState<LibraryItem | null>(null)

  if (status && !sharing) {
    return (
      <EmptyState
        title="Nothing to share with"
        message="Workflows and plugins are shared through a server. Connect to one, or serve this project, in Settings › Sync."
      />
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button size="sm" variant="primary" onClick={() => setPublishing(true)}>
          Publish…
        </Button>
      </div>
      <DataTable
        dense
        columns={COLUMNS}
        rows={items ?? []}
        getRowId={(i) => `${i.kind}/${i.name}`}
        isLoading={isLoading}
        error={error ? errorMessage(error) : undefined}
        emptyTitle="The library is empty"
        actions={(i) => (
          <span className="inline-flex gap-1">
            <Button
              size="sm"
              disabled={i.here === 'same'}
              onClick={() => setInstalling(i)}
            >
              {i.here === 'different' ? 'Update…' : 'Install…'}
            </Button>
            <Button size="sm" variant="danger" onClick={() => setRemoving(i)}>
              Remove
            </Button>
          </span>
        )}
        actionsLabel="Actions"
        actionsWidth="180px"
      />
      {installing && (
        <InstallDialog item={installing} onClose={() => setInstalling(null)} />
      )}
      {publishing && <PublishDialog onClose={() => setPublishing(false)} />}
      {removing && (
        <ConfirmDialog
          title={`Remove ${removing.filename} from the library?`}
          body="Copies already installed stay where they are."
          confirmLabel="Remove"
          variant="danger"
          isPending={unpublish.isPending}
          warning={unpublish.error ? errorMessage(unpublish.error) : undefined}
          onClose={() => {
            unpublish.reset()
            setRemoving(null)
          }}
          onConfirm={() =>
            unpublish.mutate(
              { kind: removing.kind, name: removing.name, force: false },
              { onSuccess: () => setRemoving(null) },
            )
          }
        />
      )}
    </div>
  )
}

function stateOf(here: LibraryItem['here']): string {
  if (here === 'same') return 'Unchanged'
  if (here === 'different') return 'Replaces yours'
  return 'New'
}

/** Shows what installing writes, which of it is code and what starts by
 * itself, before anything is written. A plugin needs an explicit "I trust it":
 * it runs on this computer from then on. */
function InstallDialog({
  item,
  onClose,
}: {
  item: LibraryItem
  onClose: () => void
}) {
  const [replace, setReplace] = useState(false)
  const [trusted, setTrusted] = useState(false)
  const { data: plan, error } = useInstallPlan(item, replace)
  const { install } = useLibraryActions()
  const [done, setDone] = useState<InstallPlan | null>(null)
  const differs = plan?.steps.some((s) => s.here === 'different')
  const nothingToDo = plan?.steps.every((s) => s.here === 'same')

  return (
    <Modal onClose={onClose} size="xl">
      <ModalHeader onClose={onClose}>Install {item.filename}</ModalHeader>
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
                      {stateOf(s.here)} · v{s.item.version}
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
                      <PluginCode name={s.item.name} />
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
            {plan.blocked.length > 0 && (
              <ul role="alert" className="space-y-1 text-danger">
                {plan.blocked.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            )}
            {differs && (
              <CheckRow
                compact
                title="Replace the files that differ here"
                checked={replace}
                onChange={setReplace}
              />
            )}
            {plan.runs_code && !nothingToDo && (
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
                {done.warnings
                  .filter((w) => !plan.warnings.includes(w))
                  .map((w) => ` ${w}`)}
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
              nothingToDo ||
              (plan.runs_code && !trusted) ||
              install.isPending
            }
            onClick={() =>
              install.mutate(
                { kind: item.kind, name: item.name, replace },
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

function PluginCode({ name }: { name: string }) {
  const { data, error } = useLibraryItem('plugin', name)
  if (error) return <p className="text-danger">{errorMessage(error)}</p>
  if (!data) return <p className="text-fg-muted">Loading…</p>
  return (
    <pre className="mt-2 max-h-80 overflow-auto rounded bg-canvas-inset p-2 font-mono text-xs">
      {data.content}
    </pre>
  )
}

/** Publish a workflow (with the plugins its steps use) or a plugin. */
function PublishDialog({ onClose }: { onClose: () => void }) {
  const { data: workflows } = useWorkflows()
  const { data: plugins } = usePlugins()
  const { publish } = useLibraryActions()
  const [choice, setChoice] = useState('')
  const [withPlugins, setWithPlugins] = useState(true)
  const [sent, setSent] = useState<LibraryItem[] | null>(null)
  const ownPlugins = (plugins ?? []).filter((p) => !p.builtin && p.filename)
  const [kind, name] = choice.split(':') as [string, string | undefined]

  return (
    <Modal onClose={onClose} size="md">
      <ModalHeader onClose={onClose}>Publish to the library</ModalHeader>
      <ModalBody className="space-y-4 text-sm">
        <Field label="What">
          <Select value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="">Choose…</option>
            <optgroup label="Workflows">
              {(workflows ?? []).map((w) => (
                <option key={w.stem} value={`workflow:${w.stem}`}>
                  {w.name}
                </option>
              ))}
            </optgroup>
            {ownPlugins.length > 0 && (
              <optgroup label="Plugins">
                {ownPlugins.map((p) => (
                  <option
                    key={p.filename!}
                    value={`plugin:${p.filename!.replace(/\.py$/, '')}`}
                  >
                    {p.name}
                  </option>
                ))}
              </optgroup>
            )}
          </Select>
        </Field>
        {kind === 'workflow' && (
          <CheckRow
            compact
            title="Send the plugins it uses too"
            checked={withPlugins}
            onChange={setWithPlugins}
          />
        )}
        {publish.error && (
          <p role="alert" className="text-danger">
            {errorMessage(publish.error)}
          </p>
        )}
        {sent && (
          <p role="status" className="text-success">
            Published{' '}
            {sent.map((i) => `${i.filename} (v${i.version})`).join(', ')}.
          </p>
        )}
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>{sent ? 'Close' : 'Cancel'}</Button>
        {!sent && (
          <Button
            variant="primary"
            disabled={!name || publish.isPending}
            onClick={() =>
              publish.mutate(
                { kind, name: name!, with_plugins: withPlugins },
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
