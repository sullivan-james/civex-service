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
import { SAVED_KINDS } from '../../utils/savedKinds'
import { viewNameError } from '../../utils/naming'
import { LAYOUTS, LAYOUT_SHORT } from '../../utils/exportLayouts'
import { errorMessage } from '../../lib/errors'

const LAYOUT_HINT: Record<FilesLayout, string> = {
  tree: 'Give each record a folder of its own, inside the folder of the record it belongs to.',
  grouped: 'Gather the files of each kind of record into one folder.',
  flat: 'Put every file in one folder.',
}

/** Asks for a saved filter's name -- free text, in the user's own words. */
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
        <Field label="Name" error={name ? invalid : undefined}>
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

/** A kind's saved filters: one chip each (click to apply, click again to
 * drop). The applied one can be renamed or deleted, and -- when the filter
 * on screen isn't exactly a saved one -- saved over or saved as new. They
 * belong to the kind, not to whoever made them. */
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
      <Subheading as="span">Saved filters</Subheading>
      {views.map((v) => {
        const active = activeView?.id === v.id
        const Icon = SAVED_KINDS.filter.icon
        return (
          <Chip
            key={v.id}
            selected={active}
            onClick={() => (active ? onClear() : onApply(v))}
          >
            <Icon size={12} aria-hidden="true" />
            {v.name}
          </Chip>
        )
      })}
      {activeView && (
        <Menu
          items={[
            { label: 'Rename…', onClick: () => setDialog('rename') },
            ...(filesLayout && onFilesLayout
              ? LAYOUTS.filter((l) => l !== filesLayout).map((l) => ({
                  label: `Export files: ${LAYOUT_SHORT[l]}`,
                  hint: LAYOUT_HINT[l],
                  onClick: () => onFilesLayout(l),
                }))
              : []),
            {
              label: 'Delete…',
              variant: 'danger',
              onClick: () => setDialog('delete'),
            },
          ]}
          align="left"
          trigger={({ toggle, open }) => (
            <IconButton
              icon={MoreVertical}
              size="sm"
              aria-label={`Manage saved filter ${activeView.name}`}
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
          <Save size={12} /> Save this filter
        </Button>
      )}

      {dialog === 'save-as' && (
        <ViewNameDialog
          title="Save this filter"
          confirmLabel="Save"
          isPending={pending}
          error={error}
          onClose={close}
          onSave={(name) => onSaveAs(name, close)}
        />
      )}
      {dialog === 'rename' && activeView && (
        <ViewNameDialog
          title="Rename saved filter"
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
          title="Delete saved filter"
          body={`Delete "${activeView.name}"? No records are affected.`}
          confirmLabel="Delete"
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
