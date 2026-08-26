import type { Alert, CitizenReport, SensorStation } from '@/types'

export const DEMO_ALERTS: Alert[] = [
  {
    id: 'a1',
    severity: 'evacuation',
    title: 'Immediate evacuation advised — Zone Z-07',
    zone: 'Z-07',
    district: 'Churachandpur',
    message:
      'M2 dynamic risk model: 72h failure probability 0.87. Antecedent rainfall index exceeded threshold; move households in the lower sector to designated shelters.',
    probability: 0.87,
    issuedAt: '2026-08-21T06:30:00Z',
    expiresAt: '2026-08-24T06:30:00Z',
    status: 'active',
  },
  {
    id: 'a2',
    severity: 'warning',
    title: 'Slope movement detected — Tiltmeter T-114',
    zone: 'Z-03',
    district: 'Aizawl',
    message: 'Tiltmeter T-114 angular displacement accelerating beyond baseline; field team verification requested.',
    probability: 0.64,
    issuedAt: '2026-08-21T04:10:00Z',
    status: 'active',
  },
  {
    id: 'a3',
    severity: 'warning',
    title: 'Heavy rainfall forecast — pore pressure rising',
    zone: 'Z-11',
    district: 'Gangtok',
    message: 'IMD rainfall forecast: 210 mm/48h. Piezometer PZO-GGT-07 pore pressure rising steadily.',
    probability: 0.58,
    issuedAt: '2026-08-21T02:45:00Z',
    status: 'acknowledged',
    acknowledgedAt: '2026-08-21T03:20:00Z',
  },
  {
    id: 'a4',
    severity: 'watch',
    title: 'Elevated soil moisture — monitoring continued',
    zone: 'Z-05',
    district: 'Shillong',
    message: 'Antecedent soil moisture index at 0.71. Watch level maintained; next model run at 18:00 IST.',
    probability: 0.42,
    issuedAt: '2026-08-20T18:00:00Z',
    status: 'active',
  },
]

export const DEMO_STATIONS: SensorStation[] = [
  { id: 's1', code: 'AWS-MNP-01', type: 'AWS', district: 'Imphal West', status: 'online', battery: 96, lastReading: '38.2 mm/h rainfall' },
  { id: 's2', code: 'TILT-AIZ-14', type: 'Tiltmeter', district: 'Aizawl', status: 'online', battery: 88, lastReading: '0.42 deg/day' },
  { id: 's3', code: 'PZO-GGT-07', type: 'Piezometer', district: 'Gangtok', status: 'online', battery: 91, lastReading: '6.4 kPa' },
  { id: 's4', code: 'AWS-SHG-03', type: 'AWS', district: 'East Khasi Hills', status: 'maintenance', battery: 64, lastReading: 'no data' },
  { id: 's5', code: 'GNSS-JRT-09', type: 'GNSS', district: 'Jaintia Hills', status: 'offline', battery: 12, lastReading: 'last seen 2d ago' },
]

export const DEMO_REPORTS: CitizenReport[] = [
  { id: 'r1', code: 'GSN-2026-A41F', reportType: 'crack', village: 'Mawsynram', district: 'East Khasi Hills', severity: 'high', description: 'New crack across village road, ~4 m long and widening.', status: 'verified', priorityScore: 78, createdAt: '2026-08-21T05:12:00Z' },
  { id: 'r2', code: 'GSN-2026-B77C', reportType: 'debris', village: 'Churachandpur', district: 'Pherzawl', severity: 'medium', description: 'Debris flow partially blocking the link road after overnight rain.', status: 'assigned', priorityScore: 65, createdAt: '2026-08-21T03:40:00Z' },
  { id: 'r3', code: 'GSN-2026-C92D', reportType: 'bulge', village: 'Aizawl', district: 'Aizawl', severity: 'medium', description: 'Bulging retaining wall below the school compound.', status: 'submitted', priorityScore: 54, createdAt: '2026-08-21T01:22:00Z' },
  { id: 'r4', code: 'GSN-2026-D15E', reportType: 'rockfall', village: 'Kohima', district: 'Kohima', severity: 'low', description: 'Small rockfall on NH-2 bend; cleared by locals.', status: 'resolved', priorityScore: 31, createdAt: '2026-08-20T16:05:00Z' },
]

export function makeDemoReportCode(): string {
  const hex = Math.random().toString(16).slice(2, 8).toUpperCase()
  return `GSN-${new Date().getFullYear()}-${hex}`
}
