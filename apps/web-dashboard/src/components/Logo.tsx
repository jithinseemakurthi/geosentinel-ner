/**
 * GeoSentinel-NER official logo.
 * Geometry per brand spec: navy tile, sky summit, orange ridge, red hazard beacon
 * (beacon emits a soft radar ping — remove the two `logo-alert-*` circles for a static mark).
 */
export default function Logo({ className = '', title = 'GeoSentinel-NER' }: { className?: string; title?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" width="40" height="40" className={className} role="img" aria-label={title}>
      <title>{title}</title>
      <rect width="40" height="40" rx="9" fill="#12162A"/>
      {/* Sky summit */}
      <path d="M20 9 L12.85 20 L29.75 24 Z" fill="#38BDF8"/>
      {/* Orange ridge */}
      <path d="M12.85 20 L7 29 L33 29 L29.75 24 Z" fill="#F97316" transform="translate(1,2)"/>
      {/* Hazard beacon: static core + radar ping */}
      <circle className="logo-alert-ring" cx="30.75" cy="26" r="1.8" fill="none" stroke="#EF4444" strokeWidth="1"/>
      <circle cx="30.75" cy="26" r="1.8" fill="#EF4444"/>
    </svg>
  )
}
