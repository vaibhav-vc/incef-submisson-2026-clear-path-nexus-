import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { assertPublicBuildEnvironment } from './src/lib/authConfiguration'

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), 'VITE_'), ...process.env }
  assertPublicBuildEnvironment(env)
  const backendProxyTarget = env.VITE_BACKEND_PROXY_TARGET || 'http://localhost:8000'
  return {
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: backendProxyTarget,
        changeOrigin: true,
      },
      '/health': { target: backendProxyTarget, changeOrigin: true },
      '/ready': { target: backendProxyTarget, changeOrigin: true },
    },
  },
  }
})
