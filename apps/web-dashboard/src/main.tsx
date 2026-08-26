import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import { applyTheme, resolveInitialTheme } from '@/lib/theme'

// Apply persisted or system theme before first paint
applyTheme(resolveInitialTheme())

// Follow OS preference only while the user hasn't made an explicit choice
const prefersDark = window.matchMedia('(prefers-color-scheme: dark)')
prefersDark.addEventListener('change', e => {
  if (!localStorage.getItem('theme')) {
    applyTheme(e.matches ? 'dark' : 'light')
  }
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
