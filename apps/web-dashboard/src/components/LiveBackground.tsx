interface Props {
  live?: boolean
  hasCritical?: boolean
  intensity?: number // 0-1 (kept for API compat)
}

/**
 * Ambient backdrop — deliberately minimal.
 * A faint engineering grid plus a barely-visible top tint that shifts red
 * only while a critical alert is active. No decorative motion otherwise.
 */
export default function LiveBackground({ hasCritical = false }: Props) {
  return (
    <div aria-hidden className="fixed inset-0 z-0 pointer-events-none">
      {/* engineering grid */}
      <div
        className="absolute inset-0 opacity-[0.35]"
        style={{
          backgroundImage:
            'linear-gradient(to right, rgba(148,163,184,0.035) 1px, transparent 1px), linear-gradient(to bottom, rgba(148,163,184,0.035) 1px, transparent 1px)',
          backgroundSize: '56px 56px',
          maskImage: 'radial-gradient(ellipse 90% 70% at 50% 0%, black 30%, transparent 80%)',
          WebkitMaskImage: 'radial-gradient(ellipse 90% 70% at 50% 0%, black 30%, transparent 80%)',
        }}
      />
      {/* critical tint */}
      {hasCritical && (
        <div
          className="absolute inset-x-0 top-0 h-64 animate-pulse-soft"
          style={{ background: 'radial-gradient(60% 100% at 50% 0%, rgba(239,68,68,0.07), transparent 70%)' }}
        />
      )}
    </div>
  )
}
