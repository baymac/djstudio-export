import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { homedir } from 'os'
import { resolve } from 'path'

// All downloaded course data lives under ~/Music/dj-tools/<course-id>/
// Serving the parent lets us fetch /<course-id>/lessons.json etc. for any course.
const djToolsDir = resolve(homedir(), 'Music', 'dj-tools')

export default defineConfig({
  plugins: [react()],
  publicDir: djToolsDir,
  server: {
    open: false,
    // portless sets PORT + HOST env vars to bind vite to its chosen port
    port: process.env.PORT ? parseInt(process.env.PORT) : 5173,
    host: process.env.HOST ?? 'localhost',
  },
})
