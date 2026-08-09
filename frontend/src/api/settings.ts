import { api } from './client'

export interface UISettings {
  show_advanced: boolean
}

export const settingsApi = {
  getUi: () => api.get<UISettings>('/settings/ui'),
  updateUi: (show_advanced: boolean) =>
    api.patch<UISettings>('/settings/ui', { show_advanced }),
}
