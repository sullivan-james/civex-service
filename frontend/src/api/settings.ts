import { api } from './client'

export interface UISettings {
  show_advanced: boolean
}

export interface RetentionSettings {
  purge_after_days: number
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

export const settingsApi = {
  getShortcut: () => api.get<ShortcutState>('/settings/shortcut'),
  createShortcut: () => api.post<ShortcutState>('/settings/shortcut', {}),
  getMap: () => api.get<MapSettings>('/settings/map'),
  updateMap: (body: MapSettings) =>
    api.patch<MapSettings>('/settings/map', body),
  getUi: () => api.get<UISettings>('/settings/ui'),
  updateUi: (show_advanced: boolean) =>
    api.patch<UISettings>('/settings/ui', { show_advanced }),
  getRetention: () => api.get<RetentionSettings>('/settings/retention'),
  updateRetention: (purge_after_days: number) =>
    api.patch<RetentionSettings>('/settings/retention', { purge_after_days }),
}
