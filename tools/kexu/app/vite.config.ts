import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  base: './', plugins: [react()],
  server: { watch: { ignored: ['**/.tools/**', '**/android/**', '**/release/**', '**/test-results/**', '**/playwright-report/**'] } },
  build: { chunkSizeWarningLimit: 1000, rollupOptions: { output: { manualChunks: { react: ['react', 'react-dom'] } } } },
});
