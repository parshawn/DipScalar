import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/trending-batches': 'http://127.0.0.1:8001',
      '/batch-charts': 'http://127.0.0.1:8001',
      '/agent': 'http://127.0.0.1:8001',
      '/execute': 'http://127.0.0.1:8001',
      '/prices-history': 'http://127.0.0.1:8001',
      '/candles': 'http://127.0.0.1:8001',
      '/batches': 'http://127.0.0.1:8001',
    },
  },
})
