import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const target = process.env.QIL_API_PROXY_TARGET ?? 'http://127.0.0.1:8000'
const proxy = { '/api': { target, changeOrigin: false } }

export default defineConfig({
  appType: 'spa',
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    // Preserve Host/Origin for same-origin sessions and CSRF.
    proxy,
  },
  preview: { host: '127.0.0.1', strictPort: true, proxy },
})
