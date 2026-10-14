/** What a person may do here, said once: the names in `domain/permissions.py`.
 * The app disables what may not be done and says why; a project in a folder on
 * this machine allows everything, which is assumed until the server answers. */
export type Action =
  | 'read'
  | 'write_records'
  | 'change_structure'
  | 'manage_files'
  | 'delete'
  | 'manage_members'

export const PROJECT = 'project'

/** Each action, with what it lets a person do, as the server words it; the
 * local wording until the server answers. */
export const ACTIONS: Record<Action, string> = {
  read: 'see the project',
  write_records:
    'add, change and restore records, and save filters and exports',
  change_structure: 'change kinds of record, their fields and collections',
  manage_files: 'add files',
  delete: 'delete records, collections and kinds of record',
  manage_members: 'decide who may do what',
}

export type Allowed = Readonly<Record<string, readonly string[]>>

export const EVERYTHING: Allowed = Object.fromEntries(
  (Object.keys(ACTIONS) as Action[]).map((a) => [a, [PROJECT]]),
)

/** Whether `action` may be done: anywhere when no collection is named (so an
 * action limited to some collections answers false), else in that one. */
export function can(
  allowed: Allowed,
  action: Action,
  collectionId?: string | null,
): boolean {
  const scopes = allowed[action] ?? []
  if (scopes.includes(PROJECT)) return true
  return !!collectionId && scopes.includes(`collection:${collectionId}`)
}

/** Why a control is off: the one sentence beside a disabled control. */
export function notAllowed(
  action: Action,
  words: Partial<Record<string, string>> = ACTIONS,
): string {
  return `You may not ${words[action] ?? action} here.`
}

/** Where `scopes` let an action be done, in words: everywhere, or the named
 * collections. */
export function whereAllowed(
  scopes: readonly string[],
  names: ReadonlyMap<string, string>,
): string {
  if (scopes.includes(PROJECT)) return 'Everywhere in this project'
  const collections = scopes
    .filter((s) => s.startsWith('collection:'))
    .map((s) => s.slice('collection:'.length))
    .map((id) => names.get(id) ?? 'a collection')
  return collections.length === 1
    ? `In ${collections[0]}`
    : `In ${collections.slice(0, -1).join(', ')} and ${collections[collections.length - 1]}`
}
