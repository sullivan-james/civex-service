import './index.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { ThemeProvider } from './hooks/useTheme'
import { applyUiSize } from './hooks/useUiSize'
import { ToastProvider } from './components/ui/ToastProvider'
import { ApiError } from './api/client'

const queryClient = new QueryClient({
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

// The chosen size before the first paint, so a page never flashes at another.
applyUiSize()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </ToastProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
