import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  // Relative asset paths: the same build works at / (npm run dev, preview) and at the site's
  // /apps/<id>/, and the storage API is found next to the page (src/lib/storage.ts).
  base: './',
  plugins: [react(), tailwindcss()],
});
