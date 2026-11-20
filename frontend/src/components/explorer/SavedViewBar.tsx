import { useState } from 'react'
import type { FilesLayout, View } from '../../api/views'
import {
  Button,
  ConfirmDialog,
  Field,
  FormError,
  Input,
  Menu,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  IconButton,
  Chip,
  Subheading,
} from '../ui'
import { MoreVertical, Save } from '../ui/icons'
import { SAVED_KINDS, viewKind } from '../../utils/savedKinds'
import { viewNameError } from '../../utils/naming'
import { LAYOUTS, LAYOUT_SHORT } from '../../utils/exportLayouts'
import { errorMessage } from '../../lib/errors'

const LAYOUT_HINT: Record<FilesLayout, string> = {
  tree: 'Give each record a folder of its own, inside the folder of the record it belongs to.',
  grouped: 'Gather the files of each kind of record into one folder.',
  flat: 'Put every file in one folder.',
}

/** Asks for a view's name -- free text, in the user's own words. */
function ViewNameDialog({
  title,
  intro,
  confirmLabel,
  initialName = '',
  onSave,
  onClose,
  isPending,
  error,
}: {
  title: string
  intro?: string
  confirmLabel: string
  initialName?: string
  onSave: (name: string) => void
  onClose: () => void
  isPending: boolean
  error: unknown
}) {
  const [name, setName] = useState(initialName)
  const invalid = viewNameError(name)
  return (
    <Modal onClose={onClose} size="sm" dismissible={!isPending}>
      <ModalHeader onClose={onClose}>{title}</ModalHeader>
      <ModalBody className="space-y-3">
        {intro && <p className="text-sm text-fg-muted">{intro}</p>}
        <Field label="View name" error={name ? invalid : undefined}>
          <Input
            autoFocus
            value={name}
            placeholder="Selections missing a table"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !invalid) onSave(name.trim())
            }}
          />
        </Field>
        {error != null && <FormError message={errorMessage(error)} />}
      </ModalBody>
      <ModalFooter>
        <Button size="sm" onClick={onClose} disabled={isPending}>
          Cancel
        </Button>
        <Button
          size="sm"
          variant="primary"
          disabled={!!invalid || isPending}
          onClick={() => onSave(name.trim())}
        >
          {isPending ? 'Saving…' : confirmLabel}
        </Button>
      </ModalFooter>
    </Modal>
  )
}

type Dialog = 'save-as' | 'rename' | 'delete' | null

/** A schema's saved filters: one chip per view (click to apply, click again
 * to drop). The applied view can be renamed or deleted, and -- when the
 * selection isn't exactly a saved view -- saved over or saved as new. Views
 * belong to the schema, not to whoever made them. */
export function SavedViewBar({
  views,
  activeView,
  modified,
  hasSelection,
  onApply,
  onClear,
  onSave,
  onSaveAs,
  onRename,
  onDelete,
  filesLayout,
  onFilesLayout,
  pending,
  error,
}: {
  views: View[]
  activeView: View | null
  modified: boolean
  /** Whether there is any filter/sort/column choice worth saving. */
  hasSelection: boolean
  onApply: (view: View) => void
  onClear: () => void
  onSave: () => void
  onSaveAs: (name: string, done: () => void) => void
  onRename: (name: string, done: () => void) => void
  onDelete: (done: () => void) => void
  /** How this view's files are laid out when exported, and a way to change it;
   * given only where the listed records have file fields. */
  filesLayout?: FilesLayout
  onFilesLayout?: (layout: FilesLayout) => void
  pending: boolean
  error: unknown
}) {
  const [dialog, setDialog] = useState<Dialog>(null)
  const close = () => setDialog(null)
  if (views.length === 0 && !hasSelection) return null
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Subheading as="span">Saved</Subheading>
      {views.map((v) => {
        const active = activeView?.id === v.id
        // What it gives you: a List of records or an Analysis of them.
        const kind = SAVED_KINDS[viewKind(v)]
        const Icon = kind.icon
        return (
          <Chip
            key={v.id}
            selected={active}
            onClick={() => (active ? onClear() : onApply(v))}
          >
            <Icon size={12} aria-hidden="true" />
            {v.name}
            <span className="text-xs font-normal opacity-70">{kind.word}</span>
          </Chip>
        )
      })}
      {activeView && (
        <Menu
          items={[
            { label: 'Rename view…', onClick: () => setDialog('rename') },
            ...(filesLayout && onFilesLayout
              ? LAYOUTS.filter((l) => l !== filesLayout).map((l) => ({
                  label: `Export files: ${LAYOUT_SHORT[l]}`,
                  hint: LAYOUT_HINT[l],
                  onClick: () => onFilesLayout(l),
                }))
              : []),
            {
              label: 'Delete view…',
              variant: 'danger',
              onClick: () => setDialog('delete'),
            },
          ]}
          align="left"
          trigger={({ toggle, open }) => (
            <IconButton
              icon={MoreVertical}
              size="sm"
              aria-label={`Manage view ${activeView.name}`}
              aria-expanded={open}
              aria-haspopup="menu"
              onClick={toggle}
            />
          )}
        />
      )}
      {activeView && modified && (
        <>
          <span className="text-xs text-attention">modified</span>
          <Button size="sm" onClick={onSave} disabled={pending}>
            Save
          </Button>
        </>
      )}
      {hasSelection && (
        <Button size="sm" onClick={() => setDialog('save-as')}>
          <Save size={12} /> Save as view…
        </Button>
      )}

      {dialog === 'save-as' && (
        <ViewNameDialog
          title="Save as view"
          confirmLabel="Save view"
          isPending={pending}
          error={error}
          onClose={close}
          onSave={(name) => onSaveAs(name, close)}
        />
      )}
      {dialog === 'rename' && activeView && (
        <ViewNameDialog
          title="Rename view"
          confirmLabel="Rename"
          initialName={activeView.name}
          isPending={pending}
          error={error}
          onClose={close}
          onSave={(name) => onRename(name, close)}
        />
      )}
      {dialog === 'delete' && activeView && (
        <ConfirmDialog
          title="Delete view"
          body={`Delete the saved view "${activeView.name}"? This only removes the saved filter — no records are affected.`}
          confirmLabel="Delete view"
          variant="danger"
          isPending={pending}
          warning={error != null ? errorMessage(error) : undefined}
          onConfirm={() => onDelete(close)}
          onClose={close}
        />
      )}
    </div>
  )
}
