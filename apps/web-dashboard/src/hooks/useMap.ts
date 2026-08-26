import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import { DEFAULT_CENTER } from '@/lib/districts'

const MAP_STYLE = 'https://demotiles.maplibre.org/style.json'

export interface UseMapOptions {
  containerRef: React.RefObject<HTMLDivElement>
  center?: [number, number]
  zoom?: number
  onMoveEnd?: (e: unknown) => void
}

/**
 * Creates a MapLibre map bound to containerRef and cleans up on unmount or
 * when center/zoom change. Center is compared by value (string key), not by
 * array identity, so inline literals don't trigger spurious re-creation.
 */
export function useMap({ containerRef, center, zoom = 11, onMoveEnd }: UseMapOptions) {
  const [map, setMap] = useState<maplibregl.Map | null>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const centerKey = center ? center.join(',') : ''

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const parsedCenter: [number, number] = centerKey
      ? (centerKey.split(',').map(Number) as [number, number])
      : [DEFAULT_CENTER.lng, DEFAULT_CENTER.lat]

    const m = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      center: parsedCenter,
      zoom,
      attributionControl: false,
    })

    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

    if (onMoveEnd) {
      m.on('moveend', onMoveEnd)
    }

    mapRef.current = m
    setMap(m)

    return () => {
      mapRef.current?.remove()
      mapRef.current = null
      setMap(null)
    }
    // containerRef is a stable ref object; its .current presence gates init
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [centerKey, zoom])

  return { map }
}
