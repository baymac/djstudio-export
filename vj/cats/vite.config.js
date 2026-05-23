import { defineConfig } from 'vite';

export default defineConfig({
  base: '/',
  server: {
    open: false,
    port: process.env.PORT ? parseInt(process.env.PORT) : 5173,
    host: process.env.HOST ?? 'localhost',
  },
});
