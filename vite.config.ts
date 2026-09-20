import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dashboard / workflows page only. The extension has its own UI (a side
// panel, see extension/sidepanel.html) — there is no toolbar popup here.
export default defineConfig({
  plugins: [react()],
});
