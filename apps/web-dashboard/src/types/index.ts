export type Severity = 'watch' | 'warning' | 'evacuation' | 'advisory'

export interface Alert {
  id: string
  severity: Severity
  title: string
  zone: string
  district: string
  message: string
  probability: number
  issuedAt: string
  expiresAt?: string
  status: 'active' | 'acknowledged' | 'expired'
  acknowledgedAt?: string | null
}

export interface SensorStation {
  id: string
  code: string
  type: 'AWS' | 'Tiltmeter' | 'Piezometer' | 'SoilMoisture' | 'GNSS'
  district: string
  status: 'online' | 'maintenance' | 'offline'
  battery: number
  lastReading: string
}

export interface CitizenReport {
  id: string
  code: string
  reportType: 'crack' | 'bulge' | 'subsidence' | 'debris' | 'rockfall' | 'road_block' | 'excavation' | 'water_spring' | 'other'
  village: string
  district: string
  severity: string
  description?: string
  status: 'submitted' | 'verified' | 'assigned' | 'resolved'
  priorityScore: number
  createdAt: string
  reporterName?: string
}

export interface GeoPoint {
  lng: number
  lat: number
}

export interface AuthUser {
  username: string
  role: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}
