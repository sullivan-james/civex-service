import { api } from './client'

export interface UISettings {
  show_advanced: boolean
}

export interface RetentionSettings {
  purge_after_days: number
}

export const settingsApi = {
  getUi: () => api.get<UISettings>('/settings/ui'),
  updateUi: (show_advanced: boolean) =>
    api.patch<UISettings>('/settings/ui', { show_advanced }),
  getRetention: () => api.get<RetentionSettings>('/settings/retention'),
  updateRetention: (purge_after_days: number) =>
    api.patch<RetentionSettings>('/settings/retention', { purge_after_days }),
}
