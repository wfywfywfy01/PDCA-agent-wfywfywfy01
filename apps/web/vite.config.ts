import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// PDCA 工作台前端（P1）：开发期经 /api 代理到 8767 FastAPI，
// 生产构建 base 由 VITE_SPA_BASE 控制（.env.production=/app/，
// 与 FastAPI app/spa/router.py 的挂载点一致）。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const base = env.VITE_SPA_BASE || '/'
  return {
    base,
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8767',
          changeOrigin: false,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
    },
  }
})
