import { QueryClient } from '@tanstack/react-query'
import { ApiError } from './api/client'

/** The query client the app runs on (`main.tsx`, and `embed.tsx` when mounted). */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // A 4xx (not found, bad request, ...) means the request itself is
        // wrong, not a transient failure -- retrying it unchanged just burns
        // ~7s of backoff (react-query's default 3 retries) before a "not
        // found" page can even render. Keep the default retry count for
        // everything else (network blips, 5xx).
        retry: (failureCount, error) =>
          error instanceof ApiError && error.status >= 400 && error.status < 500
            ? false
            : failureCount < 3,
      },
    },
  })
}
