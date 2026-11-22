import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    proxy: {
      // REST and WebSocket (/api/v1/ws/*) both live under /api
      '/api': {
        target: 'http://localhost:8000',
        // keep the browser's Host (localhost:5173) so it matches the Origin header; the
        // backend rejects cross-origin unsafe requests and WebSockets (see README)
        changeOrigin: false,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
