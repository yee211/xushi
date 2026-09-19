import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'
import { readFileSync } from 'node:fs'

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'))

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  // 版本号唯一来源是 package.json，构建时注入，避免源码里写死过期版本
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
    __APP_VERSION_CODE__: JSON.stringify(pkg.versionCode ?? 0),
  },
  cacheDir: '.vite',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8001' },
  },
})
