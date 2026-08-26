import { useState, useEffect, useRef } from 'react'
import { login } from '@/services/api'
import Logo from '@/components/Logo'

export default function LoginPage({ onLogin }: { onLogin: (username: string, demo: boolean) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // --- Live ring: continuous spin + mouse parallax tilt ---
  const ringRef = useRef<HTMLDivElement>(null)
  const targetTilt = useRef({ x: 0, y: 0 })
  const curTilt = useRef({ x: 0, y: 0 })

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let raf = 0
    let spin = 0
    let last = performance.now()
    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now
      spin += dt * 4 // deg/sec → one full revolution every ~90 s
      // ease tilt toward cursor target (buttery smooth)
      curTilt.current.x += (targetTilt.current.x - curTilt.current.x) * 0.055
      curTilt.current.y += (targetTilt.current.y - curTilt.current.y) * 0.055
      if (ringRef.current) {
        ringRef.current.style.transform =
          `rotate(${spin.toFixed(2)}deg) rotateX(${curTilt.current.y.toFixed(2)}deg) rotateY(${curTilt.current.x.toFixed(2)}deg)`
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])

  function handleMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    const nx = e.clientX / window.innerWidth - 0.5   // -0.5 … 0.5
    const ny = e.clientY / window.innerHeight - 0.5
    targetTilt.current.x = nx * 10                    // ±5° yaw
    targetTilt.current.y = -ny * 8                    // ±4° pitch
  }

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
    <div className="relative min-h-full flex items-center justify-center px-4 overflow-hidden" onMouseMove={handleMouseMove}>
      {/* Live galactic background — the RING spins continuously; scene tilts with your cursor */}
      <div className="absolute inset-0 -z-10 overflow-hidden" aria-hidden="true" style={{ perspective: '1400px' }}>
        {/* Oversized layer so rotation never reveals corners */}
        <div
          ref={ringRef}
          className="absolute -inset-[30%]"
          style={{
            backgroundImage: 'url("/galactic-ring.jpg")',
            backgroundSize: 'cover',
            backgroundPosition: 'center',
            backgroundRepeat: 'no-repeat',
            filter: 'brightness(0.55) saturate(1.15)',
            willChange: 'transform',
            transformOrigin: '50% 50%',
            transform: 'rotate(0deg)',
          }}
        />
        {/* Contrast overlay + vignette */}
        <div className="absolute inset-0" style={{ background: 'radial-gradient(ellipse at center, rgba(0,0,0,0.35) 0%, rgba(0,0,0,0.72) 100%)' }} />
        {/* Subtle noise texture */}
        <div className="absolute inset-0 opacity-[0.03]" style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E")`,
        }} />
      </div>

      <div className="w-full max-w-sm animate-slide-up relative z-10">
        <div className="mb-8 text-center">
          <Logo className="mx-auto mb-3 h-14 w-14 rounded-xl drop-shadow-[0_10px_34px_rgba(56,189,248,0.35)]" />
          <h1 className="text-xl font-extrabold tracking-tight text-white drop-shadow-lg">
            GeoSentinel<span className="text-gradient">-NER</span>
          </h1>
          <p className="mt-1 text-xs text-slate-300/80">Landslide Early Warning · Officer & Citizen Portal</p>
        </div>

        <form onSubmit={handleSubmit} className="solid-panel space-y-4 p-6">
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
            API offline? Any username + 8-char password enters demo mode.
            <br />
            Accounts lock for 15 min after 5 failed attempts.
          </p>
        </form>
      </div>
    </div>
  )
}
