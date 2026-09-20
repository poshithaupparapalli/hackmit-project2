import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        // Dashboard / workflows page.
        main: 'index.html',
        // Extension toolbar popup — Anika points default_popup at the built
        // popup.html. No manifest.json is written from this repo.
        popup: 'popup.html',
      },
    },
  },
});
