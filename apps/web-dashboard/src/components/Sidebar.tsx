import { useEffect, useState } from 'react'
import Logo from '@/components/Logo'

export type Tab = 'overview' | 'map' | 'reports' | 'capitals'

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'overview', label: 'Overview', icon: '◈' },
  { id: 'map', label: 'Live Map', icon: '◉' },
  { id: 'reports', label: 'Citizen Reports', icon: '▤' },
  { id: 'capitals', label: 'Capitals', icon: '🏛' },
]

export default function Sidebar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    const handleResize = () => setCollapsed(window.innerWidth < 1024)
    handleResize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  return (
    <>
      {/* Mobile bottom nav */}
      <nav className="fixed bottom-0 left-0 right-0 z-40 md:hidden bg-slate-950 border-t border-slate-800">
        <div className="grid grid-cols-4">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => { onChange(t.id); setMobileOpen(false) }}
              aria-current={active === t.id ? 'page' : undefined}
              className={`flex flex-col items-center gap-1 px-1 py-2.5 text-[11px] transition ${
                active === t.id
                  ? 'text-emerald-400'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <span className="text-xl">{t.icon}</span>
              <span className="w-full truncate text-center leading-tight">{t.label}</span>
            </button>
          ))}
        </div>
      </nav>

      {/* Desktop sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-30 flex flex-col w-60 shrink-0 transition-all duration-300 ease-out border-r border-slate-800 bg-slate-950 md:w-64 ${
          collapsed ? '-translate-x-full md:translate-x-0' : 'translate-x-0'
        }`}
        aria-label="Main navigation"
      >
        <div className="flex items-center justify-between gap-3 px-5 py-5 border-b border-slate-800/70">
          <div className="flex items-center gap-3 min-w-0">
            <Logo className="h-10 w-10 flex-shrink-0 drop-shadow-[0_6px_22px_rgba(56,189,248,0.30)]" />
            {!collapsed && (
              <div className="min-w-0">
                <div className="text-sm font-extrabold tracking-tight truncate">
                  GeoSentinel<span className="text-gradient">-NER</span>
                </div>
                <div className="text-[11px] text-slate-500 truncate">Landslide Early Warning</div>
              </div>
            )}
          </div>
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="flex-shrink-0 rounded-lg px-2 py-1.5 text-slate-500 transition hover:bg-slate-800/50 hover:text-slate-300 md:hidden"
            aria-label={collapsed ? 'Open sidebar' : 'Close sidebar'}
          >
            {collapsed ? '☰' : '✕'}
          </button>
        </div>

        <nav className="mt-2 flex-1 overflow-y-auto px-3" role="navigation" aria-label="Main">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => { onChange(t.id); setMobileOpen(false) }}
              aria-current={active === t.id ? 'page' : undefined}
              title={collapsed ? t.label : undefined}
              className={`relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all duration-200 group ${
                active === t.id
                  ? 'font-semibold text-cyan-200'
                  : 'text-slate-400 hover:text-slate-100 hover:bg-white/[.04]'
              }`}
            >
              {/* active gradient bar */}
              {active === t.id && (
                <span
                  className="absolute left-0 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r-full animate-gradient-x"
                  style={{ backgroundImage: 'linear-gradient(180deg,#22d3ee,#818cf8,#c084fc)' }}
                  aria-hidden="true"
                />
              )}
              <span
                className={`text-lg flex-shrink-0 transition-transform duration-200 ${
                  active === t.id ? 'scale-110' : 'group-hover:scale-110 opacity-80'
                }`}
              >
                {t.icon}
              </span>
              {!collapsed && <span className="truncate">{t.label}</span>}
            </button>
          ))}
        </nav>

        {!collapsed && (
          <div className="mt-auto space-y-3 p-4 border-t border-slate-800/70">
            <div className="rounded-lg border border-slate-800/70 bg-slate-900 p-3 text-xs">
              <div className="mb-1 flex items-center gap-2">
                <span className="live-dot h-2 w-2 rounded-full bg-emerald-400" aria-hidden="true" />
                <span className="font-semibold text-slate-300">API Gateway</span>
              </div>
              <span className="text-slate-500">localhost:8000 · realtime</span>
            </div>
            <div className="text-[11px] leading-relaxed text-slate-600">
              v0.1.0 · development
              <br />
              North Eastern Region, India
            </div>
          </div>
        )}
      </aside>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-20 bg-slate-950/90 md:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}
    </>
  )
}