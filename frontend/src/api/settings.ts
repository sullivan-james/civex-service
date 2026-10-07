import { api } from './client'

export interface UISettings {
  show_advanced: boolean
}

/** How long this project keeps things. Nothing is removed by itself: a clean-up
 * applies these. Null keeps that kind forever. */
export interface RetentionSettings {
  /** Deleted items can be restored for this many days. */
  purge_after_days: number
  /** Whether a clean-up permanently deletes them after that. */
  auto_purge_deleted: boolean
  audit_days: number | null
  run_days: number | null
}

export interface MapSettings {
  tile_url: string | null
  attribution: string | null
}

export interface ShortcutState {
  exists: boolean
  /** Where the shortcut is (or would go); null when there is no Desktop. */
  path: string | null
}

/** Whether the desktop app's `civex` can be typed in a terminal. */
export interface CommandLineState {
  /** Only the desktop app's civex; a uv, pipx or pip install already is one. */
  available: boolean
  on_path: boolean
  /** The folder put on PATH (Windows) or the link made (macOS, Linux). */
  where: string | null
  /** Another civex a terminal would find first. */
  shadowed_by: string | null
  /** What is still to do; blank if nothing. */
  note: string
}

/** Who changes made here are recorded as, for this user and project. */
export interface Identity {
  name: string | null
  chosen: string | null
  default: string | null
}

export const settingsApi = {
  getIdentity: () => api.get<Identity>('/settings/identity'),
  updateIdentity: (name: string | null) =>
    api.patch<Identity>('/settings/identity', { name }),
  getShortcut: () => api.get<ShortcutState>('/settings/shortcut'),
  getCommandLine: () => api.get<CommandLineState>('/settings/command-line'),
  addCommandLine: () =>
    api.post<CommandLineState>('/settings/command-line', {}),
  removeCommandLine: () =>
    api.delete<CommandLineState>('/settings/command-line'),
  createShortcut: () => api.post<ShortcutState>('/settings/shortcut', {}),
  getMap: () => api.get<MapSettings>('/settings/map'),
  updateMap: (body: MapSettings) =>
    api.patch<MapSettings>('/settings/map', body),
  getUi: () => api.get<UISettings>('/settings/ui'),
  updateUi: (show_advanced: boolean) =>
    api.patch<UISettings>('/settings/ui', { show_advanced }),
  getRetention: () => api.get<RetentionSettings>('/settings/retention'),
  updateRetention: (settings: Partial<RetentionSettings>) =>
    api.patch<RetentionSettings>('/settings/retention', settings),
}
