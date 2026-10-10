import { defineConfig } from 'vite';

export default defineConfig({
  publicDir: 'public',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: { background: 'src/background.ts' },
      output: { entryFileNames: '[name].js', format: 'es' },
    },
  },
});
