/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const api = process.env.PLANNER_API ?? 'http://localhost:8010'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': api } },
  preview: { port: 4173, proxy: { '/api': api } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
