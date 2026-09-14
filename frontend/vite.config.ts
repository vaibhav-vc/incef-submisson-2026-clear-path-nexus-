import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { assertPublicBuildEnvironment } from './src/lib/authConfiguration'
import { resolveRuntimeMode } from './src/lib/runtimeMode'

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), 'VITE_'), ...process.env }
  assertPublicBuildEnvironment(env)
  const namedMode = mode === 'online' || mode === 'offline-judge' ? mode : undefined
  const runtimeMode = resolveRuntimeMode(env.VITE_APP_MODE || namedMode, env.VITE_LOCAL_DEMO_MODE)
  const backendProxyTarget = env.VITE_BACKEND_PROXY_TARGET || 'http://localhost:8000'
  return {
    plugins: [
      react(),
      tailwindcss(),
      ...(runtimeMode === 'offline-judge' ? [{
        name: 'offline-judge-network-boundary',
        transformIndexHtml() {
          return [{
            tag: 'meta',
            attrs: {
              'http-equiv': 'Content-Security-Policy',
              content: "default-src 'self' data: blob:; connect-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'",
            },
            injectTo: 'head-prepend' as const,
          }]
        },
      }] : []),
    ],
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
