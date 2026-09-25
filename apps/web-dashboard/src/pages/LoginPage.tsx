import { useState } from 'react'
import { login } from '@/services/api'
import Logo from '@/components/Logo'
import Globe3D from '@/components/Globe3D'

export default function LoginPage({ onLogin }: { onLogin: (username: string, demo: boolean) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)


  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!username.trim() || password.length < 8) {
      setError('Username required · password must be at least 8 characters')
      return
    }
    setBusy(true)
    setError('')
    const res = await login({ username: username.trim(), password })
    setBusy(false)
    if (res.ok) {
      onLogin(username.trim(), res.demo)
    } else {
      setError('Incorrect username or password')
    }
  }

  return (
    <div className="relative min-h-full flex items-center justify-center px-4 overflow-hidden">
      <Globe3D />

      <div className="w-full max-w-sm animate-slide-up relative z-10">
        <div className="mb-7 text-center">
          <Logo className="mx-auto mb-3 h-14 w-14 rounded-xl" />
          <h1 className="text-xl font-bold tracking-tight text-white">
            GeoSentinel<span className="text-[#38BDF8]">-NER</span>
          </h1>
          <p className="mt-1 text-xs text-slate-300/85">Landslide Early Warning · Officer & Citizen Portal</p>
          <div className="mt-3 inline-flex items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 backdrop-blur-md">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-70" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[#22C55E]" />
            </span>
            <span className="text-[10px] font-semibold uppercase tracking-widest text-emerald-300/90">
              Live · 5 NE stations · satellite linked
            </span>
          </div>
        </div>

        <div className="relative">
          <div
            aria-hidden
            className="pointer-events-none absolute -inset-3 -z-10 rounded-[1.7rem] bg-gradient-to-tr from-sky-500/20 via-indigo-500/14 to-cyan-400/14 blur-2xl"
          />
          <form onSubmit={handleSubmit} className="solid-panel space-y-4 p-6 backdrop-blur-xl">
          <div>
            <label htmlFor="username" className="label text-slate-200">Username or email</label>
            <input
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              className="input"
              placeholder="officer@ner.gov.in"
            />
          </div>
          <div>
            <label htmlFor="password" className="label text-slate-200">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="input"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="btn-primary w-full rounded-lg py-2.5"
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </button>

          <p className="text-center text-[11px] leading-relaxed text-slate-400/80">
            Sign in with your officer credentials.
            <br />
            Accounts lock for 15 min after 5 failed attempts.
          </p>
          </form>
          <p className="mt-3 text-center text-[10px] tracking-wide text-slate-500/70">
            Drag the globe · scroll to zoom · network arcs show live inter-station links
          </p>
        </div>
      </div>
    </div>
  )
}
