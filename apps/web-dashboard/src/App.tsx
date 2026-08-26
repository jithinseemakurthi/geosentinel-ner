import { useEffect, useMemo, useState } from 'react'
import { Toaster, toast } from 'react-hot-toast'
import Sidebar from '@/components/Sidebar'
import type { Tab } from '@/components/Sidebar'
import Overview from '@/components/Overview'
import MapView from '@/components/MapView'
import ReportsTable from '@/components/ReportsTable'
import AlertDetail from '@/components/AlertDetail'
import ReportForm from '@/components/ReportForm'
import { ReportDetail } from '@/components/ReportDetail'
import SensorDetail from '@/components/SensorDetail'
import CapitalsPanel from '@/components/CapitalsPanel'
import ShortcutsModal from '@/components/ShortcutsModal'
import LoginPage from '@/pages/LoginPage'
import { fetchAlerts, fetchReports, fetchDevSession, getAccessToken } from '@/services/api'
import { useRealtime, type RealtimeEvent } from '@/hooks/useRealtime'
import { useCommandPalette, CommandPalette, type Command } from '@/hooks/useCommandPalette'
import { getActiveTheme, toggleTheme as toggleThemePref, type Theme } from '@/lib/theme'
import { DEMO_STATIONS } from '@/data/demo'
import type { Alert, AuthUser, CitizenReport, SensorStation } from '@/types'

export default function App() {
  const [tab, setTab] = useState<Tab>(() => {
    const t = new URLSearchParams(window.location.search).get('tab')
    return t === 'map' || t === 'reports' || t === 'capitals' ? (t as Tab) : 'overview'
  })
  const [user, setUser] = useState<AuthUser | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [reports, setReports] = useState<CitizenReport[]>([])
  const [alertsLive, setAlertsLive] = useState(false)
  const [selected, setSelected] = useState<Alert | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [reportDetail, setReportDetail] = useState<CitizenReport | null>(null)
  const [sensorDetail, setSensorDetail] = useState<SensorStation | null>(null)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [theme, setThemeState] = useState<Theme>(() => getActiveTheme())

  function handleToggleTheme() {
    const next = toggleThemePref()
    setThemeState(next)
    toast.success(next === 'dark' ? 'Dark theme' : 'Light theme', { icon: next === 'dark' ? '🌙' : '☀️', duration: 1500 })
  }

  const commands = useMemo<Command[]>(() => [
    { id: 'nav-overview', label: 'Go to Overview', shortcut: 'G O', icon: '◈', category: 'Navigation', action: () => setTab('overview') },
    { id: 'nav-map', label: 'Go to Live Map', shortcut: 'G M', icon: '◉', category: 'Navigation', action: () => setTab('map') },
    { id: 'nav-reports', label: 'Go to Reports', shortcut: 'G R', icon: '▤', category: 'Navigation', action: () => setTab('reports') },
    { id: 'nav-capitals', label: 'Go to Capitals', shortcut: 'G C', icon: '🏛', category: 'Navigation', action: () => setTab('capitals') },
    { id: 'new-report', label: 'Submit New Report', shortcut: 'N', icon: '➕', category: 'Actions', action: () => setFormOpen(true) },
    { id: 'refresh', label: 'Refresh Data', icon: '↻', category: 'Actions', action: () => { void refreshAll(); toast.success('Data refreshed', { duration: 1500 }) } },
    { id: 'toggle-theme', label: `Switch to ${getActiveTheme() === 'dark' ? 'light' : 'dark'} theme`, shortcut: 'T', icon: '🌓', category: 'View', action: handleToggleTheme },
    { id: 'sign-out', label: 'Sign Out', icon: '🚪', category: 'Account', action: () => setUser(null) },
    { id: 'help', label: 'Keyboard Shortcuts', shortcut: '?', icon: '❓', category: 'Help', action: () => setShortcutsOpen(true) },
  ], [])

  const {
    open: paletteOpen,
    setOpen: setPaletteOpen,
    query,
    setQuery,
    filtered,
    selectedIndex: paletteIndex,
    inputRef: paletteInputRef,
  } = useCommandPalette({ commands, onClose: () => {} })

  // Global keyboard shortcuts (ignored while typing in inputs)
  useEffect(() => {
    let gPending = false
    let timer: number | undefined
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable)) return
      if (e.metaKey || e.ctrlKey || e.altKey) return

      if (gPending) {
        window.clearTimeout(timer)
        gPending = false
        switch (e.key.toLowerCase()) {
          case 'o': setTab('overview'); e.preventDefault(); break
          case 'm': setTab('map'); e.preventDefault(); break
          case 'r': setTab('reports'); e.preventDefault(); break
          case 'c': setTab('capitals'); e.preventDefault(); break
        }
        return
      }
      if (e.key.toLowerCase() === 'g') {
        gPending = true
        timer = window.setTimeout(() => { gPending = false }, 1000)
        return
      }
      switch (e.key) {
        case 'n': setFormOpen(true); break
        case 't': handleToggleTheme(); break
        case '?': setShortcutsOpen(true); break
      }
    }
    window.addEventListener('keydown', handler)
    return () => {
      window.removeEventListener('keydown', handler)
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [])

  async function refreshAll() {
    const alertsResult = await fetchAlerts()
    setAlerts(alertsResult.data)
    setAlertsLive(alertsResult.live)
    const reportsResult = await fetchReports()
    setReports(reportsResult.data)
  }

  function handleEvent(event: RealtimeEvent) {
    switch (event.type) {
      case 'alert.new': {
        toast(event.payload?.title ? String(event.payload.title) : 'New landslide alert issued', {
          icon: '⚠',
          duration: 6000,
        })
        const p = (event.payload ?? {}) as Record<string, unknown>
        const liveAlert: Alert = {
          id: typeof p.id === 'string' ? p.id : crypto.randomUUID(),
          severity: (p.severity as Alert['severity']) ?? 'advisory',
          title: typeof p.title === 'string' ? p.title : 'Live alert',
          zone: typeof p.zone === 'string' ? p.zone : 'LIVE',
          district: typeof p.district === 'string' ? p.district : '—',
          message: typeof p.message === 'string' ? p.message : '',
          probability: typeof p.probability === 'number' ? p.probability : 0.5,
          issuedAt: typeof p.issued_at === 'string' ? p.issued_at : new Date().toISOString(),
          status: 'active',
          acknowledgedAt: null,
        }
        void (async () => {
          await refreshAll()
          setAlerts(prev => [liveAlert, ...prev.filter(a => a.id !== liveAlert.id)])
        })()
        break
      }
      case 'alert.update': {
        const id = event.payload?.id
        if (typeof id === 'string') {
          setAlerts((prev) =>
            prev.map((a) =>
              a.id === id
                ? {
                    ...a,
                    status: (event.payload?.status as Alert['status']) ?? a.status,
                    acknowledgedAt:
                      (event.payload?.acknowledged_at as string | undefined) ?? a.acknowledgedAt,
                  }
                : a,
            ),
          )
        }
        break
      }
      case 'report.new':
      case 'report.update':
      case 'sensor.reading':
        void refreshAll()
        break
      default:
        break
    }
  }

  const wsStatus = useRealtime(user !== null, getAccessToken(), handleEvent)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('demo') === '1') {
      setUser((u) => u ?? { username: 'demo', role: 'citizen (demo)' })
      if (params.get('form') === '1') setFormOpen(true)
    }
  }, [])

  // Demo/dev logins have no DB-backed token — mint one so WebSocket realtime works
  useEffect(() => {
    if (user && !getAccessToken()) void fetchDevSession()
  }, [user])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('alert') === '1' && alerts.length > 0) {
      setSelected((s) => s ?? alerts[0])
    }
  }, [alerts])

  useEffect(() => {
    if (!user) return
    void refreshAll()
  }, [user])

  const stations = useMemo(
    () => ({ online: DEMO_STATIONS.filter((s) => s.status === 'online').length, total: DEMO_STATIONS.length }),
    [],
  )

  if (!user) {
    return (
      <LoginPage
        onLogin={(username, demo) => setUser({ username, role: demo ? 'citizen (demo)' : 'district_officer' })}
      />
    )
  }

  const badge = wsStatus === 'online' || alertsLive
    ? { text: wsStatus === 'online' ? 'LIVE — realtime connected' : 'LIVE — API connected', cls: 'border-emerald-400/40 bg-emerald-500/10 text-emerald-300 shadow-[0_0_18px_rgba(52,211,153,0.15)]' }
    : { text: 'DEMO DATA — API offline', cls: 'border-amber-400/40 bg-amber-500/10 text-amber-300 shadow-[0_0_18px_rgba(251,191,36,0.12)]' }

  return (
    <div className="flex h-full">
      <Sidebar active={tab} onChange={setTab} />
      <main className="flex min-w-0 flex-1 flex-col md:ml-64">
        <header className="flex items-center justify-between border-b border-slate-800/70 px-6 py-4">
          <div>
            <h1 className="text-lg font-extrabold capitalize tracking-tight">
              <span className={tab === 'map' ? 'text-gradient' : ''}>{tab === 'map' ? 'Live Map' : tab}</span>
            </h1>
            <p className="text-xs text-slate-500">
              Landslide early warning · M1 susceptibility / M2 dynamic risk / M3 CV triage
            </p>
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            <span className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold ${badge.cls}`}>
              <span
                className={`h-2 w-2 rounded-full ${
                  wsStatus === 'online' ? 'live-dot bg-emerald-400' : badge.text.startsWith('LIVE') ? 'bg-emerald-400' : 'bg-amber-400'
                }`}
              />
              <span className="hidden sm:inline">{badge.text}</span>
              <span className="sm:hidden">{wsStatus === 'online' || alertsLive ? 'LIVE' : 'DEMO'}</span>
            </span>
            <button
              onClick={handleToggleTheme}
              className="grid h-9 w-9 place-items-center rounded-lg border border-slate-800/70 text-base transition-all duration-200 hover:border-cyan-500/40 hover:shadow-[0_0_16px_rgba(34,211,238,0.18)] hover:-translate-y-0.5"
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              title="Toggle theme (T)"
            >
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>
            <button
              onClick={() => setShortcutsOpen(true)}
              className="hidden h-9 w-9 place-items-center rounded-lg border border-slate-800/70 font-mono text-sm text-slate-400 transition-all duration-200 hover:border-cyan-500/40 hover:text-cyan-300 hover:shadow-[0_0_16px_rgba(34,211,238,0.18)] hover:-translate-y-0.5 sm:grid"
              aria-label="Keyboard shortcuts"
              title="Keyboard shortcuts (?)"
            >
              ?
            </button>
            <button
              onClick={() => setFormOpen(true)}
              className="btn-primary rounded-lg px-3 py-2 text-sm sm:px-4"
            >
              + New Report
            </button>
            <div className="relative">
              <button
                onClick={() => setUserMenuOpen(o => !o)}
                className="grid h-8 w-8 cursor-pointer place-items-center rounded-full text-sm font-bold text-white ring-2 ring-transparent transition-all duration-200 hover:ring-cyan-400/50"
                style={{ backgroundImage: 'linear-gradient(135deg,#0EA5E9,#38BDF8 60%,#7DD3FC)' }}
                aria-haspopup="menu"
                aria-expanded={userMenuOpen}
                aria-label="Account menu"
              >
                {user.username.slice(0, 2).toUpperCase()}
              </button>
              {userMenuOpen && (
                <>
                  <div className="fixed inset-0 z-10" aria-hidden="true" onClick={() => setUserMenuOpen(false)} />
                  <div role="menu" className="solid-panel absolute right-0 z-20 mt-2 w-44 p-3 opacity-100 animate-slide-up">
                    <div className="truncate text-sm font-bold">{user.username}</div>
                    <div className="text-xs capitalize text-slate-500">{user.role}</div>
                    <button
                      onClick={() => { setUserMenuOpen(false); setUser(null) }}
                      role="menuitem"
                      className="mt-2 w-full rounded-md border border-slate-700/70 px-2 py-1.5 text-xs text-slate-300 transition-all duration-200 hover:border-rose-500/50 hover:text-rose-300"
                    >
                      Sign out
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-4 pb-24 sm:p-6 md:pb-6">
          {tab === 'overview' && (
            <Overview
              alerts={alerts}
              stations={stations}
              reportsToday={reports.length}
              live={wsStatus === 'online' || alertsLive}
              onAlertClick={(a: Alert) => setSelected(a)}
            />
          )}
          {tab === 'map' && (
            <MapView
              alerts={alerts}
              stations={DEMO_STATIONS}
              onAlertClick={a => setSelected(a)}
              onStationClick={s => setSensorDetail(s)}
            />
          )}
          {tab === 'reports' && <ReportsTable reports={reports} onOpenDetail={(r) => setReportDetail(r)} />}
          {tab === 'capitals' && (
            <CapitalsPanel />
          )}
        </div>
      </main>

      <AlertDetail
        alert={selected}
        onClose={() => setSelected(null)}
        onAcknowledge={(id) =>
          setAlerts((prev) => prev.map((a: Alert) => (a.id === id ? { ...a, status: 'acknowledged', acknowledgedAt: new Date().toISOString() } : a)))
        }
      />
      {reportDetail && (
        <ReportDetail
          report={reportDetail}
          onClose={() => setReportDetail(null)}
          onStatusChange={(id, status) =>
            setReports((prev) => prev.map((r: CitizenReport): CitizenReport => (r.id === id ? { ...r, status: status as CitizenReport['status'] } : r)))
          }
        />
      )}
      {sensorDetail && (
        <SensorDetail station={sensorDetail} onClose={() => setSensorDetail(null)} />
      )}
      <ReportForm open={formOpen} onClose={() => setFormOpen(false)} onCreated={(r) => setReports((prev) => [r, ...prev])} />

      <Toaster
        position="top-right"
        toastOptions={{
          style: {
            background: 'var(--bg-elevated)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border-primary)',
          },
        }}
      />
      <ShortcutsModal open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        query={query}
        setQuery={setQuery}
        filtered={filtered}
        selectedIndex={paletteIndex}
        inputRef={paletteInputRef}
      />
    </div>
  )
}
