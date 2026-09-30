import { defineConfig } from 'vite'
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
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
