import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/agent': 'http://127.0.0.1:8001', '/execute': 'http://127.0.0.1:8001' } },
})
