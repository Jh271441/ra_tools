import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { coldStartPlugin } from './build/coldStart.mjs';

export default defineConfig({
  base: '/sim/',
  plugins: [react(), coldStartPlugin()],
  server: {
    port: 5174,
    proxy: {
      '/sim/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/sim\/api/, '/api'),
      },
    },
  },
});
