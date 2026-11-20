import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  // 相对路径：站点无论挂在域名根路径还是子路径，资源都能正确加载。
  base: './',
  plugins: [react(), tailwindcss()],
})
