import type { GeoPoint } from '@/types'

/**
 * District headquarters coordinates for the North Eastern Region, India.
 * Mirrors packages/geosentinel-shared/geosentinel_shared/districts.py
 * (the canonical backend copy) — keep both in sync when adding districts.
 */
export const DISTRICT_COORDS: Record<string, GeoPoint> = {
  Churachandpur: { lng: 93.68, lat: 24.2 },
  Aizawl: { lng: 92.7176, lat: 23.7271 },
  Gangtok: { lng: 88.6065, lat: 27.3389 },
  Shillong: { lng: 91.8933, lat: 25.5788 },
  'Imphal West': { lng: 93.9368, lat: 24.817 },
  Imphal: { lng: 93.9368, lat: 24.817 },
  'East Khasi Hills': { lng: 91.36, lat: 25.46 },
  Kohima: { lng: 94.1086, lat: 25.6751 },
  Itanagar: { lng: 93.6053, lat: 27.0844 },
  Dispur: { lng: 91.7898, lat: 26.1433 },
  Agartala: { lng: 91.2868, lat: 23.8315 },
}

/** Regional fallback center (approx. NER centroid) for unknown districts. */
export const DEFAULT_CENTER: GeoPoint = { lng: 92.4, lat: 25.6 }

export function districtCenter(district?: string | null): GeoPoint {
  return (district && DISTRICT_COORDS[district]) || DEFAULT_CENTER
}
