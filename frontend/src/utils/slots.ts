import type { ComponentType } from 'react'

/** The few places a host's extension may draw inside the app, by name.
 *
 * Most of what a host adds needs nothing here: what the server does
 * (`useFeatures`), what a person may do (`usePermissions`) and who they are
 * (`useAccount`) are data the app already reads, and managing members, billing
 * and the like live on the host's own pages, linked to. A slot is for the rest:
 * something that must be drawn inside a project page. Keep the list short; a
 * new name is a promise to every host. */
export const SLOTS = {
  /** Beside a workflow's own actions (its page header). Props: `{ workflow }`,
   * the workflow's name. */
  'workflow.actions': 'Beside a workflow’s actions',
  /** A section of Settings of its own: registered with a `label` (and `id`),
   * shown in the section list and at `/settings/x/<id>`. No props. */
  'settings.sections': 'A section of Settings',
  /** In a collection's header. Props: `{ collectionId }`. */
  'collection.header': 'In a collection’s header',
  /** In a record page's header. Props: `{ recordId }`. */
  'record.header': 'In a record’s header',
  /** Above how storage is used (Settings → Storage, or the Storage section a
   * host adds). No props. */
  'storage.summary': 'Above how storage is used',
} as const

export type SlotName = keyof typeof SLOTS

export interface SlotEntry {
  /** Unique within its slot; registering the same id again replaces it. */
  id: string
  /** What it is called where a slot lists entries (Settings sections). */
  label?: string
  // Each slot documents its props; an extension's component takes those.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Component: ComponentType<any>
}

type Listener = () => void

const entries = new Map<SlotName, readonly SlotEntry[]>()
const listeners = new Set<Listener>()

function isSlot(name: string): name is SlotName {
  return Object.prototype.hasOwnProperty.call(SLOTS, name)
}

/** Puts `Component` into `slot`. Returns a function that takes it out again.
 * An unknown slot name is refused, so a misspelling fails loudly in the
 * extension instead of drawing nothing. */
export function register(
  slot: string,
  Component: SlotEntry['Component'],
  options: { id?: string; label?: string } = {},
): () => void {
  if (!isSlot(slot))
    throw new Error(
      `civex has no slot "${slot}"; there are ${Object.keys(SLOTS).join(', ')}.`,
    )
  const id =
    options.id ?? Component.displayName ?? Component.name ?? 'extension'
  const entry: SlotEntry = { id, label: options.label, Component }
  entries.set(slot, [
    ...(entries.get(slot) ?? []).filter((e) => e.id !== id),
    entry,
  ])
  notify()
  return () => {
    entries.set(
      slot,
      (entries.get(slot) ?? []).filter((e) => e !== entry),
    )
    notify()
  }
}

const NONE: readonly SlotEntry[] = []

/** What is registered in `slot`, in the order it was registered. The same
 * array until something changes, so it can be a React external store. */
export function slotEntries(slot: SlotName): readonly SlotEntry[] {
  return entries.get(slot) ?? NONE
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function notify() {
  for (const listener of listeners) listener()
}

/** Empties every slot (tests). */
export function clearSlots(): void {
  entries.clear()
  notify()
}
