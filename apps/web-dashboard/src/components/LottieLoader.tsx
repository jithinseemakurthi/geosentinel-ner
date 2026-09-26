import { useEffect, useRef } from 'react'

export default function LottieLoader({ src, className = 'h-24 w-24' }: { src?: string; className?: string }) {
  const el = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let player: any = null
    let cancelled = false
    async function load() {
      try {
        // dynamic import to keep dependency optional
        const lottie: any = await import('lottie-web')
        if (cancelled) return
        if (!el.current) return
        const resp = src ? await fetch(src).then(r => r.json()) : null
        player = lottie.loadAnimation({ container: el.current, renderer: 'svg', loop: true, autoplay: true, animationData: resp ?? undefined })
      } catch {
        // lottie not available or fetch failed — ignore, fallback UI remains
      }
    }
    void load()
    return () => { cancelled = true; if (player && player.destroy) player.destroy() }
  }, [src])

  return (
    <div className={`flex items-center justify-center ${className}`}>
      <div ref={el} aria-hidden />
      {/* fallback spinner for when lottie isn't available */}
      <svg className="animate-spin h-8 w-8 text-emerald-400" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="loading">
        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" strokeOpacity="0.12" />
        <path d="M22 12a10 10 0 00-10-10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
      </svg>
    </div>
  )
}
