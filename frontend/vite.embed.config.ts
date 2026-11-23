import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

/** The second entry: the app as a function that mounts it inside another page
 * (`src/embed.tsx`). Built after the standalone app into `dist/embed/`, which
 * ships in the package's static dir next to it. The stylesheet is inside
 * `embed.js` (it is adopted into a shadow root, not linked), and React is
 * bundled, so a host needs nothing but the one module. */
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: './',
  define: { 'process.env.NODE_ENV': '"production"' },
  build: {
    outDir: 'dist/embed',
    emptyOutDir: true,
    lib: {
      entry: 'src/embed.tsx',
      formats: ['es'],
      fileName: () => 'embed.js',
    },
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
})
