import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/articles': 'http://127.0.0.1:8000',
      '/collect': 'http://127.0.0.1:8000',
      '/watchlist': 'http://127.0.0.1:8000',
      '/social': 'http://127.0.0.1:8000',
      '/export': 'http://127.0.0.1:8000'
    }
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: false,
  },
})
