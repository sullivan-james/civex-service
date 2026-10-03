import { useState } from 'react'
import type { View } from '../../api/views'
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
import { viewNameError } from '../../utils/naming'
import { errorMessage } from '../../lib/errors'

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
        return (
          <Chip
            key={v.id}
            selected={active}
            onClick={() => (active ? onClear() : onApply(v))}
          >
            {v.name}
          </Chip>
        )
      })}
      {activeView && (
        <Menu
          items={[
            { label: 'Rename view…', onClick: () => setDialog('rename') },
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
