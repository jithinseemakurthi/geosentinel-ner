import type { Alert, CitizenReport, TokenResponse } from '@/types'
import { DEMO_ALERTS, DEMO_REPORTS, makeDemoReportCode } from '@/data/demo'

const API_BASE = '/api/v1'
const TIMEOUT_MS = 2500

export interface ApiState {
  online: boolean
  token?: string
}

const state: ApiState = { online: false }

export function isOnline() {
  return state.online
}

export function getAccessToken(): string | null {
  return state.token ?? null
}

async function call<T>(path: string, init?: RequestInit): Promise<T | null> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
        ...init?.headers,
      },
    })
    if (!res.ok) return null
    state.online = true
    return (await res.json()) as T
  } catch {
    state.online = false
    return null
  } finally {
    clearTimeout(timer)
  }
}

interface LoginBody {
  username: string
  password: string
}

export async function login(body: LoginBody): Promise<{ ok: boolean; demo: boolean; token?: TokenResponse }> {
  const token = await call<TokenResponse>('/auth/login', { method: 'POST', body: JSON.stringify(body) })
  if (token?.access_token) {
    state.token = token.access_token
    return { ok: true, demo: false, token }
  }
  if (body.username && body.password.length >= 8) {
    return { ok: true, demo: true }
  }
  return { ok: false, demo: true }
}

export async function fetchAlerts(): Promise<{ data: Alert[]; live: boolean }> {
  const res = await call<{ items: Alert[] }>('/alerts')
  if (res?.items) return { data: mapAlerts(res.items), live: true }
  return { data: DEMO_ALERTS, live: false }
}

export async function acknowledgeAlert(id: string): Promise<boolean> {
  const res = await call<{ status: string }>(`/alerts/${id}/acknowledge`, { method: 'POST' })
  return res?.status === 'acknowledged'
}

export async function fetchReports(): Promise<{ data: CitizenReport[]; live: boolean }> {
  const res = await call<{ items: CitizenReport[] }>('/reports')
  if (res?.items) return { data: res.items, live: true }
  return { data: DEMO_REPORTS, live: false }
}

/** Dev-mode only: obtain a functional WS-capable token without a database */
export async function fetchDevSession(): Promise<boolean> {
  const res = await call<{ access_token?: string }>('/dev/session', { method: 'POST' })
  if (res?.access_token) {
    state.token = res.access_token
    return true
  }
  return false
}

export interface LiveWeather {
  district: string
  source: string
  observed_rainfall_24h_mm: number | null
  forecast_rainfall_next_24h_mm: number | null
  temperature_c: number | null
  humidity_pct: number | null
}

/** Live observed+forecast weather for a district (data-ingestion → Open-Meteo, keyless) */
export async function fetchLiveWeather(district: string): Promise<LiveWeather | null> {
  try {
    const res = await fetch(`/weather/current/${encodeURIComponent(district)}`)
    if (!res.ok) return null
    return (await res.json()) as LiveWeather
  } catch {
    return null
  }
}

export interface ImdNowcastEntry {
  District?: string
  State_District?: string
  State?: string
  Date?: string
  alerts_total?: number
  cats_active?: Record<string, number>
  message?: string
  impact?: string
  action?: string
  Color?: number | string
  update_time?: string
  vupto?: string
  toi?: string
}

/** Live district nowcast warnings from IMD's public GeoServer (keyless) */
export async function fetchImdNowcast(district: string): Promise<ImdNowcastEntry | null> {
  try {
    const res = await fetch(`/imd/nowcast?district=${encodeURIComponent(district)}`)
    if (!res.ok) return null
    const data = (await res.json()) as { data?: ImdNowcastEntry[] }
    return data.data?.[0] ?? null
  } catch {
    return null
  }
}

export interface ReverseGeoResult {
  label: string | null
  village: string | null
  district: string | null
  state: string | null
}

/** HERE-powered reverse geocode (server-proxied; null when offline/unconfigured) */
export async function reverseGeocode(lat: number, lng: number): Promise<ReverseGeoResult | null> {
  return call<ReverseGeoResult>(`/geo/reverse?lat=${lat}&lon=${lng}`)
}

export async function submitReport(payload: {
  reportType: string
  severity: string
  description: string
  reporterName: string
  lat: number
  lng: number
}): Promise<CitizenReport> {
  const body = {
    report_type: payload.reportType,
    severity: payload.severity,
    description: payload.description,
    reporter_name: payload.reporterName || undefined,
    geom: { type: 'Point', coordinates: [payload.lng, payload.lat] },
  }
  const res = await call<Record<string, unknown>>('/reports', { method: 'POST', body: JSON.stringify(body) })
  const serverCode = res ? (res['report_code'] as string | undefined) : undefined
  if (serverCode) {
    return {
      id: (res?.['id'] as string) ?? crypto.randomUUID(),
      code: serverCode,
      reportType: payload.reportType as CitizenReport['reportType'],
      village: '—',
      district: '—',
      severity: payload.severity,
      description: payload.description,
      status: 'submitted',
      priorityScore: Number(res?.['priority_score'] ?? 40),
      createdAt: new Date().toISOString(),
    }
  }
  const scoreBySeverity: Record<string, number> = { high: 75, medium: 55, low: 35, unknown: 40 }
  return {
    id: crypto.randomUUID(),
    code: makeDemoReportCode(),
    reportType: payload.reportType as CitizenReport['reportType'],
    village: '—',
    district: '—',
    severity: payload.severity,
    description: payload.description,
    status: 'submitted',
    priorityScore: scoreBySeverity[payload.severity] ?? 40,
    createdAt: new Date().toISOString(),
  }
}

interface RawAlert {
  id?: string
  severity?: string
  title?: string
  message?: string
  status?: string
  issued_at?: string
  expires_at?: string | null
  acknowledged_at?: string | null
  zone_id?: string | null
  probability?: number
  metadata?: Record<string, unknown> | null
}

function mapAlerts(items: RawAlert[]): Alert[] {
  return items.map((a) => ({
    id: a.id ?? crypto.randomUUID(),
    severity: (a.severity ?? 'advisory') as Alert['severity'],
    title: a.title ?? 'Alert',
    zone: a.zone_id ?? '—',
    district: (typeof a.metadata?.district === 'string' && a.metadata.district) || '—',
    message: a.message ?? '',
    probability: typeof a.probability === 'number' ? a.probability : 0.5,
    issuedAt: a.issued_at ?? new Date().toISOString(),
    expiresAt: a.expires_at ?? undefined,
    status: (a.status ?? 'active') as Alert['status'],
    acknowledgedAt: a.acknowledged_at ?? null,
  }))
}
