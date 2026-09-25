import { useCallback, useEffect, useRef, useState } from 'react'
import type { RagCollection, RagHealth, RagResponse } from '@/types/rag'
import { ragHealth, ragQuery } from '@/services/rag'
import { getCollections, loadGuidelinesFromBackend, setLiveCorpus } from '@/lib/ragIndex'
import { fetchAlerts, fetchReports } from '@/services/api'

const QUICK_PROMPTS = [
  'What is the Watch vs Warning threshold for Aizawl Ridge?',
  'Summarize active evacuation alerts and their M2 scores',
  'Which NER districts have Red IMD nowcast today?',
  'Explain M1 vs M2 vs M3 and how citizen reports are triaged',
  'What should a community do when 3-day antecedent exceeds 120mm?',
]

const COLLECTION_LABELS: Record<RagCollection, string> = {
  geosentinel_guidelines: 'Guidelines',
  geosentinel_alerts: 'Alerts',
  geosentinel_reports: 'Reports',
  geosentinel_capitals: 'Capitals',
  imd_nowcast: 'IMD Nowcast',
}

export default function RagAssistant() {
  const [health, setHealth] = useState<RagHealth | null>(null)
  const [query, setQuery] = useState('')
  const [collections, setCollections] = useState<RagCollection[]>(['geosentinel_guidelines', 'geosentinel_alerts', 'geosentinel_reports'])
  const [topK, setTopK] = useState(6)
  const [reranker, setReranker] = useState(true)
  const [rewriting, setRewriting] = useState(true)
  const [agentic, setAgentic] = useState(true)
  const [liveInternet, setLiveInternet] = useState(true)
  const [filterDistrict, setFilterDistrict] = useState('')
  const [history, setHistory] = useState<{ role: 'user' | 'assistant'; text: string; resp?: RagResponse }[]>([])
  const [busy, setBusy] = useState(false)
  const [showReasoning, setShowReasoning] = useState(true)
  const listRef = useRef<HTMLDivElement>(null)

  const [collectionInfo, setCollectionInfo] = useState(() => getCollections())
  const allCollections = collectionInfo

  useEffect(() => { void ragHealth().then(setHealth) }, [])

  // Live corpus: guidelines are NOT hardcoded — fetch from docs/guidelines via API, then hydrate live alerts/reports
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        await loadGuidelinesFromBackend()
        const [aRes, rRes] = await Promise.all([fetchAlerts(), fetchReports()])
        if (cancelled) return
        setLiveCorpus(aRes.data, rRes.data)
        setCollectionInfo(getCollections())
      } catch {
        /* keep fallback guideline corpus when live fetch fails */
        if (!cancelled) setCollectionInfo(getCollections())
      }
    })()
    return () => { cancelled = true }
  }, [])

  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' }) }, [history, busy])

  const send = useCallback(async (text: string) => {
    const t = text.trim()
    if (!t || busy) return
    setQuery('')
    // capture snapshot for history to avoid stale closure — pass previous turns as LLM context
    let snapshot: typeof history = []
    setHistory((h) => {
      snapshot = [...h, { role: 'user' as const, text: t }]
      return snapshot
    })
    setBusy(true)
    try {
      const filters: Record<string, string> | undefined = filterDistrict ? { district: filterDistrict } : undefined
      const prevHistory = snapshot.slice(0, -1).slice(-8).map((m) => ({ role: m.role as 'user' | 'assistant', content: m.text }))
      const resp = await ragQuery({ text: t, collectionNames: collections, topK, enableReranker: reranker, enableQueryRewriting: rewriting, agentic, filters, history: prevHistory, enableWebSearch: liveInternet })
      setHistory((h) => [...h, { role: 'assistant', text: resp.answer, resp }])
    } catch (e) {
      setHistory((h) => [...h, { role: 'assistant', text: `RAG error: ${e instanceof Error ? e.message : String(e)}` }])
    } finally {
      setBusy(false)
    }
  }, [busy, collections, topK, reranker, rewriting, agentic, liveInternet, filterDistrict])

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="solid-card overflow-hidden rounded-xl">
        <div className="flex flex-col gap-3 bg-gradient-to-br from-violet-500/10 via-cyan-500/10 to-emerald-500/10 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-extrabold tracking-tight">NER Knowledge Assistant <span className="text-[#38BDF8]">· cited answers · agentic · hybrid search</span></h2>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-slate-400">
              Ask about landslide thresholds, IMD alerts, M1/M2/M3 models or district risk — every answer is grounded in retrieved knowledge with citations.
            </p>
          </div>
        </div>

        {/* Status strip — live knowledge + LLM */}
        <div className="flex flex-wrap items-center gap-2 bg-slate-950/50 px-5 py-2.5 text-xs">
          <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${health?.status === 'ok' ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/30 bg-amber-500/10 text-amber-300'}`}>
            <span className={`h-2 w-2 rounded-full ${health?.status === 'ok' ? 'bg-emerald-400' : 'bg-amber-400'}`} /> {health?.status === 'ok' ? (health.deployment === 'api-gateway-llm' ? 'LLM connected — live knowledge' : health.deployment === 'library' ? 'Library mode — live DB + guidelines' : 'Knowledge index ready') : 'Index warming up…'}
          </span>
          {health && (
            <>
              <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-300">hybrid search</span>
              <span className="rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[11px] text-violet-300">reranker</span>
              <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-300">verified citations</span>
              {health.services?.llm && (
                <span className={`rounded-full border px-2 py-0.5 text-[11px] ${String(health.services.llm).includes('mock') || String(health.services.llm).includes('Mock') ? 'border-amber-500/30 bg-amber-500/10 text-amber-300' : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'}`} title={String(health.services.llm)}>
                  {String(health.services.llm).includes('mock') ? 'LLM: local fallback — set GROQ/OpenAI key in .env' : `LLM: ${String(health.services.llm).slice(0, 46)}`}
                </span>
              )}
            </>
          )}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        {/* Left — controls + data catalog */}
        <div className="space-y-4">
          <div className="solid-card rounded-xl p-4">
            <h3 className="text-sm font-bold">Collections</h3>
            <p className="text-xs text-slate-500">Choose which knowledge sources to search.</p>
            <div className="mt-3 space-y-2">
              {allCollections.map((c) => (
                <label key={c.id} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-2 text-xs hover:bg-slate-800/60">
                  <span className="flex items-center gap-2">
                    <input type="checkbox" checked={collections.includes(c.id)} onChange={(e) => setCollections((p) => e.target.checked ? [...p, c.id] : p.filter((x) => x !== c.id))} className="h-4 w-4 rounded border-slate-600 bg-slate-800 accent-violet-500" />
                    <span className="font-medium text-slate-200">{COLLECTION_LABELS[c.id] ?? c.id}</span>
                  </span>
                  <span className="rounded-full bg-slate-800 px-2 py-0.5 font-mono text-[11px] text-slate-400">{c.count}</span>
                </label>
              ))}
            </div>

            <div className="mt-4 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <label className="block text-xs"><span className="font-semibold text-slate-300">Results per answer</span>
                  <input type="range" min={2} max={10} value={topK} onChange={(e) => setTopK(Number(e.target.value))} className="mt-1 w-full accent-violet-500" />
                  <span className="text-[11px] text-slate-400">{topK} sources</span>
                </label>
                <label className="block text-xs"><span className="font-semibold text-slate-300">District filter</span>
                  <input value={filterDistrict} onChange={(e) => setFilterDistrict(e.target.value)} placeholder="e.g. Aizawl" className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 font-mono text-xs" />
                  <span className="text-[11px] text-slate-500">narrow results to one district</span>
                </label>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <label className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900 px-2 py-2 text-xs"><input type="checkbox" checked={reranker} onChange={(e) => setReranker(e.target.checked)} className="h-4 w-4 accent-violet-500" /> Precision</label>
                <label className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900 px-2 py-2 text-xs"><input type="checkbox" checked={rewriting} onChange={(e) => setRewriting(e.target.checked)} className="h-4 w-4 accent-violet-500" /> Smarter query</label>
                <label className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900 px-2 py-2 text-xs"><input type="checkbox" checked={agentic} onChange={(e) => setAgentic(e.target.checked)} className="h-4 w-4 accent-violet-500" /> Deep answer</label>
              </div>
              <label className="flex items-center gap-2 rounded-lg border border-sky-500/30 bg-sky-500/10 px-2 py-2 text-xs font-semibold text-sky-300"><input type="checkbox" checked={liveInternet} onChange={(e) => setLiveInternet(e.target.checked)} className="h-4 w-4 accent-sky-500" /> 🌐 Live internet<span className="font-normal text-sky-300/70">· GDACS + ReliefWeb + web search</span></label>
              <label className="flex items-center gap-2 text-xs text-slate-400"><input type="checkbox" checked={showReasoning} onChange={(e) => setShowReasoning(e.target.checked)} className="h-4 w-4 accent-violet-500" /> Show how the answer was built</label>
            </div>
          </div>

          <div className="solid-card rounded-xl p-4">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Knowledge base</h4>
            <div className="mt-2 rounded-lg border border-slate-800 bg-slate-900 p-2.5 text-[11px] leading-relaxed text-slate-400">
              <div>{allCollections.reduce((a, c) => a + c.count, 0)} documents indexed — live alerts/reports + guidelines from <code className="rounded bg-slate-800 px-1 py-0.5 font-mono text-[10px]">docs/guidelines</code></div>
              <div className="mt-1 text-slate-500">Guidelines served at <code className="font-mono text-[10px]">/api/v1/knowledge/guidelines</code> · alerts/reports from PostGIS live · no hardcoded data</div>
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {QUICK_PROMPTS.map((p) => (
                <button key={p} onClick={() => void send(p)} className="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-1 text-left text-[11px] text-slate-300 hover:border-violet-500/40 hover:text-violet-200">“{p}”</button>
              ))}
            </div>
          </div>
        </div>

        {/* Right — chat */}
        <div className="flex min-h-[520px] flex-col rounded-xl border border-slate-800 bg-slate-950">
          <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Chat · {collections.length} source{collections.length !== 1 ? 's' : ''}</div>
            <button onClick={() => setHistory([])} className="rounded-lg border border-slate-700 px-2.5 py-1 text-xs text-slate-400 hover:bg-slate-800">Clear</button>
          </div>

          <div ref={listRef} className="flex-1 space-y-3 overflow-y-auto p-4">
            {history.length === 0 && (
              <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-6 text-center">
                <div className="text-sm font-semibold text-slate-200">Ask about NER landslide risk — every answer is cited</div>
                <div className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-slate-500">Try: landslide thresholds, IMD colours, M1/M2/M3, or “summarize evacuation alerts”.</div>
              </div>
            )}
            {history.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${m.role === 'user' ? 'bg-violet-600 text-white' : 'border border-slate-800 bg-slate-900 text-slate-200'}`}>
                  <div className="whitespace-pre-wrap break-words">{m.text}</div>
                  {m.resp && (
                    <div className="mt-3 space-y-2 border-t border-slate-800 pt-3">
                      {(m.resp.provider || m.resp.model) && (
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[11px] ${m.resp.provider === 'remote' ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/30 bg-amber-500/10 text-amber-300'}`}>
                            {m.resp.provider === 'remote' ? `● LLM ${m.resp.model ?? 'remote'}` : m.resp.provider === 'local' ? '○ local synthesis — no LLM key' : `● ${m.resp.provider}${m.resp.model ? ` · ${m.resp.model}` : ''}`}
                          </span>
                          {m.resp.usage && <span className="font-mono text-[11px] text-slate-500">{m.resp.usage.promptTokens}↑ {m.resp.usage.completionTokens}↓ tokens</span>}
                        </div>
                      )}
                      {showReasoning && m.resp.reasoningContent && (
                        <details open className="rounded-lg border border-amber-500/20 bg-amber-500/5">
                          <summary className="cursor-pointer px-3 py-1.5 text-xs font-semibold text-amber-300">Reasoning · synthesis</summary>
                          <pre className="whitespace-pre-wrap border-t border-amber-500/20 p-2.5 font-mono text-[11px] leading-relaxed text-amber-100/80">{m.resp.reasoningContent}</pre>
                        </details>
                      )}
                      {m.resp.agenticStages && m.resp.agenticStages.length > 0 && (
                        <div className="rounded-lg border border-slate-800 bg-slate-950 p-2">
                          <div className="text-xs font-semibold text-slate-400">Agentic stages · streaming events</div>
                          <div className="mt-1.5 flex flex-wrap gap-1.5">
                            {m.resp.agenticStages.map((s, j) => (
                              <span key={j} className="rounded-full border border-violet-500/20 bg-violet-500/10 px-2 py-0.5 font-mono text-[10px] text-violet-300">{s.stage}: {s.eventType === 'stage_start' ? '▶' : '✓'} {s.content?.slice(0, 42)}</span>
                            ))}
                          </div>
                        </div>
                      )}
                      {m.resp.citations.length > 0 && (
                        <div>
                          <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">Citations · {m.resp.citations.length} (reranker scores)</div>
                          <div className="mt-1 flex flex-wrap gap-1.5">
                            {m.resp.citations.map((c) => (
                              <span key={c.chunkId} title={`${c.title} — ${c.score.toFixed(3)}`} className="inline-flex items-center gap-1 rounded-full border border-cyan-500/20 bg-cyan-500/10 px-2 py-0.5 font-mono text-[11px] text-cyan-300">
                                {c.title.slice(0, 26)} · {c.score.toFixed(2)}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      <details className="rounded-lg border border-slate-800 bg-slate-950">
                        <summary className="cursor-pointer px-3 py-1.5 text-xs font-semibold text-slate-400">Retrieval inspector · {m.resp.retrieval.length} chunks · topK={topK} · {m.resp.usage ? `${m.resp.usage.promptTokens} prompt / ${m.resp.usage.completionTokens} completion tokens` : ''}</summary>
                        <div className="max-h-40 overflow-auto border-t border-slate-800 p-2">
                          {m.resp.retrieval.map((c) => (
                            <div key={c.chunkId} className="border-b border-slate-800/50 py-1.5 last:border-0">
                              <div className="flex items-center gap-2 text-xs"><span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">{c.collection}</span> <span className="font-medium text-slate-300">{c.title}</span> <span className="ml-auto font-mono text-[11px] text-slate-500">{c.score.toFixed(3)}</span></div>
                              <div className="mt-1 text-xs leading-relaxed text-slate-500">{c.content.slice(0, 180)}…</div>
                            </div>
                          ))}
                        </div>
                      </details>
                    </div>
                  )}
                </div>
              </div>
            ))}
            {busy && <div className="flex justify-start"><div className="rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3 text-xs text-slate-400">▌ Agentic planner → retrieval → reranking → synthesis…</div></div>}
          </div>

          <div className="border-t border-slate-800 p-3">
            <div className="flex gap-2">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(query) } }}
                placeholder="Ask — e.g. What triggers a Warning for Gangtok Valley?"
                className="flex-1 rounded-xl border border-slate-700 bg-slate-900 px-4 py-2.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-violet-500/50 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
              />
              <button onClick={() => void send(query)} disabled={busy || !query.trim()} className="rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-bold text-white hover:bg-violet-500 disabled:opacity-50">Send</button>
            </div>
            <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-500">
              <span>Press Enter to send · every answer includes citations</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
