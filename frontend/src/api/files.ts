import { api } from './client'

export interface FileRef {
  sha256: string
  filename: string
  size: number
  volume: string
}

export const filesApi = {
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.upload<FileRef>('/files', form)
  },
}
