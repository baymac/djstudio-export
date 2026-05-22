import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider } from '@tanstack/react-router'
import { router } from './router'
import { loadCourses, loadLessons } from './lessonsStore'
import './index.css'

const STORAGE_KEY = 'selectedCourse'

async function boot() {
  const courses = await loadCourses()

  if (courses.length === 0) {
    document.getElementById('root')!.innerHTML = `
      <div style="font-family:monospace;padding:2rem;color:#ef4444">
        No courses found. Run the scraper first:<br/>
        <span style="color:#9ca3af">uv run helpers/download_course.py download &lt;course_url&gt;</span>
      </div>
    `
    return
  }

  // Try saved course first, then walk through the rest so a single broken
  // course (e.g. unmounted external drive) doesn't block the whole app.
  const savedId = localStorage.getItem(STORAGE_KEY)
  const ordered = [
    ...(savedId ? courses.filter(c => c.id === savedId) : []),
    ...courses.filter(c => c.id !== savedId),
  ]
  const errors: string[] = []
  let loaded = false

  for (const course of ordered) {
    try {
      await loadLessons(course.id, course.name)
      localStorage.setItem(STORAGE_KEY, course.id)
      loaded = true
      break
    } catch (err: any) {
      errors.push(`• ${course.name}: ${err.message}`)
    }
  }

  if (loaded) {
    ReactDOM.createRoot(document.getElementById('root')!).render(
      <React.StrictMode>
        <RouterProvider router={router} />
      </React.StrictMode>
    )
  } else {
    document.getElementById('root')!.innerHTML = `
      <div style="font-family:monospace;padding:2rem;color:#ef4444">
        <strong>No usable courses found.</strong><br/><br/>
        ${errors.join('<br/>')}
      </div>
    `
  }
}

boot()
