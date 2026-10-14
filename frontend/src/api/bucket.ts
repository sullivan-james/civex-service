import { api } from './client'

/** How to reach a bucket: what `PUT /store/bucket` and its check take.
 * Credentials are never here: the server takes them from its environment or
 * an AWS profile. */
export interface BucketSettings {
  bucket: string
  prefix?: string
  region?: string | null
  endpoint?: string | null
  profile?: string | null
  direct?: boolean
}

/** Where this project's files are kept (`GET /store/bucket`): a bucket, or
 * drives when `bucket` is null, and whether that may change now. */
export interface BucketStatus {
  bucket: string | null
  prefix: string
  region: string | null
  endpoint: string | null
  profile: string | null
  direct: boolean
  bucket_files: number
  bucket_bytes: number
  drive_files: number
  drive_bytes: number
  /** Files recorded on drives while a bucket is used: out of reach. */
  left_on_drives: number
  /** Only while the place being left holds no files: none are moved. */
  can_switch: boolean
  blocked: string | null
}

export interface BucketCheck {
  ok: boolean
  problems: string[]
  warnings: string[]
}

export const bucketApi = {
  get: () => api.get<BucketStatus>('/store/bucket'),
  check: (body: BucketSettings) =>
    api.post<BucketCheck>('/store/bucket/check', body),
  use: (body: BucketSettings) => api.put<BucketStatus>('/store/bucket', body),
  stopUsing: () => api.delete<BucketStatus>('/store/bucket'),
}
