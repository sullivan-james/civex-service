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
