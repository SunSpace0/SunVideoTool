import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: Number(process.env.VITE_PORT) || 18881,
    strictPort: true,
    proxy: {
      '/api': {
        target: `http://${process.env.VITE_BACKEND_HOST || '127.0.0.1'}:${process.env.VITE_BACKEND_PORT || '18880'}`,
        changeOrigin: true,
      },
    },
  },
})
