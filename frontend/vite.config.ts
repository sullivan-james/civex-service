import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: 'codemirror',
              test: /node_modules[\\/](@codemirror|@lezer|@uiw|codemirror)/,
            },
            { name: 'xterm', test: /node_modules[\\/]@xterm/ },
            {
              name: 'recharts',
              test: /node_modules[\\/](recharts|d3-|victory-vendor)/,
            },
          ],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Interaction-heavy tests take ~0.5s alone but several times that when the
    // whole suite runs in parallel; the 5s default made them fail intermittently.
    testTimeout: 15_000,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
