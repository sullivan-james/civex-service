import './index.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { ThemeProvider } from './hooks/useTheme'
import { applyUiSize } from './hooks/useUiSize'
import { ToastProvider } from './components/ui/ToastProvider'
import { createQueryClient } from './queryClient'
import { applyBootTheme, basePath } from './utils/host'
import { loadExtensions } from './utils/extensions'

const queryClient = createQueryClient()

// The chosen size before the first paint, so a page never flashes at another.
applyUiSize()
// A host's colours, likewise before the first paint.
applyBootTheme()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          {/* Under a host the app lives at its `<base href>` (`utils/host`). */}
          <BrowserRouter basename={basePath() || undefined}>
            <App />
          </BrowserRouter>
        </ToastProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)

// A host's extensions draw into named slots (`utils/slots`), which update as
// they register, so the app doesn't wait for them.
void loadExtensions()
