/**
 * In-browser RAG index — lightweight analogue of RAG Blueprint's
 * Elasticsearch/Milvus + Nemotron embedding + reranker pipeline.
 *
 * For the hosted demo we run library mode (notebooks/config.yaml):
 * - Ingestion: text-only (docs/text_only_ingest.md)
 * - Search: hybrid dense+ sparse weighted (docs/hybrid_search.md)
 * - Reranker: mock cross-encoder (ENABLE_RERANKER=True)
 * - Query rewriting: NER-aware expansion (references/configure/query-and-conversation.md)
 *
 * Embeddings are TF-IDF cosine + keyword overlap (no GPU). Replace with
 * nemotron-embedding NIM when a real rag-server is reachable at /v1/generate.
 */

import type { RagChunk, RagCollection, RagDocument } from '@/types/rag'
import type { Alert, CitizenReport } from '@/types'

// Guideline corpus — loaded dynamically from docs/guidelines via /api/v1/knowledge/guidelines.
// Kept as fallback when the backend is unreachable (offline demo).
const FALLBACK_GUIDELINE_DOCS: RagDocument[] = [
  { id: 'gsi-2023', collection: 'geosentinel_guidelines', title: 'GSI Landslide Susceptibility — NER', content: 'The Geological Survey of India classifies Aizawl Ridge, Churachandpur Basin and Gangtok Valley as high susceptibility due to shale overburden, 25–40° slopes, and >1200 mm seasonal rainfall. Mitigation: benching, shotcrete, and drainage. Monitoring requires hourly rainfall + pore pressure.', metadata: { source: 'GSI', year: 2023 } },
  { id: 'ndma-2022', collection: 'geosentinel_guidelines', title: 'NDMA Landslide Do/Don\'t — Community', content: 'Do: evacuate on warning, avoid cut slopes after 50 mm/24h. Don\'t: block drainage, build on toe of slope. Early warning thresholds: 75 mm/3d antecedent + 20 mm/12h forecast triggers Watch; 120 mm/3d + 40 mm/12h triggers Warning.', metadata: { source: 'NDMA', year: 2022 } },
  { id: 'imd-sop', collection: 'imd_nowcast', title: 'IMD Nowcast — NER colour codes', content: 'IMD nowcast colours: Green (no action), Yellow (watch), Orange (prepare), Red (take action). NER districts Aizawl, Imphal, Shillong, Gangtok are covered at 3-hourly refresh. State_District and cat mapping in /imd/nowcast.', metadata: { source: 'IMD', year: 2024 } },
  { id: 'sentinel-m1', collection: 'geosentinel_guidelines', title: 'GeoSentinel M1 — Susceptibility', content: 'M1 is a static susceptibility model (slope, lithology, landcover, distance-to-road). Scores 0–1, updated quarterly. It feeds M2 dynamic risk.', metadata: { source: 'GeoSentinel', year: 2024 } },
  { id: 'sentinel-m2', collection: 'geosentinel_guidelines', title: 'GeoSentinel M2 — Dynamic Risk', content: 'M2 heuristic: 0.45·f12 + 0.35·a3/100 + 0.20·a7/200 clipped 0–1. f12 is Open-Meteo next-12h forecast, a3/a7 are 3d/7d antecedents. Thresholds: advisory <0.30 < watch <0.50 < warning <0.75 < evacuation.', metadata: { source: 'GeoSentinel', year: 2024 } },
  { id: 'capitals-ner', collection: 'geosentinel_capitals', title: 'NER Capitals — administrative map', content: 'NER capitals: Aizawl (Mizoram, 23.73N 92.72E), Imphal (Manipur 24.81N 93.94E), Shillong (Meghalaya 25.58N 91.88E), Kohima (Nagaland), Itanagar (Arunachal), Agartala (Tripura), Gangtok (Sikkim), Guwahati gateway city. Districts listed in packages/geosentinel-shared.', metadata: { source: 'Survey of India', year: 2024 } },
]
// Active guideline set — replaced when /api/v1/knowledge/guidelines succeeds
let activeGuidelines: RagDocument[] = [...FALLBACK_GUIDELINE_DOCS]
let CORPUS: RagDocument[] = [...activeGuidelines]

let _cachedAlerts: Alert[] = []
let _cachedReports: CitizenReport[] = []

function rebuildCorpus() {
  const alertDocs: RagDocument[] = _cachedAlerts.slice(0, 12).map((a) => ({
    id: `alert-${a.id}`,
    collection: 'geosentinel_alerts' as RagCollection,
    title: `${a.severity.toUpperCase()} · ${a.district} — ${a.title}`,
    content: `${a.message} Severity ${a.severity}, probability ${a.probability}, zone ${a.zone}, district ${a.district}. Issued ${a.issuedAt}. Status ${a.status}. M2 threshold logic applies.`,
    metadata: { district: a.district, severity: a.severity, zone: a.zone, status: a.status },
  }))
  const reportDocs: RagDocument[] = _cachedReports.slice(0, 12).map((r) => ({
    id: `report-${r.id}`,
    collection: 'geosentinel_reports' as RagCollection,
    title: `Report ${r.code} · ${r.district} · ${r.reportType}`,
    content: `${r.description ?? ''} Type ${r.reportType}, severity ${r.severity}, district ${r.district}, village ${r.village}, status ${r.status}, priority ${r.priorityScore}. Citizen triage via M3.`,
    metadata: { district: r.district, severity: r.severity, reportType: r.reportType, status: r.status },
  }))
  CORPUS = [...activeGuidelines, ...alertDocs, ...reportDocs]
}

export function setGuidelineDocs(docs: RagDocument[]): void {
  if (!docs?.length) return
  activeGuidelines = docs
  rebuildCorpus()
}

export async function loadGuidelinesFromBackend(): Promise<boolean> {
  try {
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), 2000)
    const res = await fetch('/api/v1/knowledge/guidelines', { signal: ctrl.signal })
    clearTimeout(t)
    if (!res.ok) return false
    const j = (await res.json()) as { items?: RagDocument[] }
    if (j.items && Array.isArray(j.items) && j.items.length) {
      // sanitize: keep only required fields
      const docs: RagDocument[] = j.items.map((d: RagDocument) => ({
        id: String(d.id),
        collection: d.collection as RagCollection,
        title: String(d.title),
        content: String(d.content),
        metadata: (d.metadata as Record<string, string | number>) ?? {},
      }))
      setGuidelineDocs(docs)
      return true
    }
    return false
  } catch {
    return false
  }
}

export function setLiveCorpus(alerts: Alert[], reports: CitizenReport[]): void {
  _cachedAlerts = alerts
  _cachedReports = reports
  rebuildCorpus()
}

function tokenize(s: string): string[] {
  return s.toLowerCase().replace(/[^a-z0-9\u00C0-\u024F]+/g, ' ').trim().split(/\s+/).filter(Boolean)
}

function tf(tokens: string[]): Map<string, number> {
  const m = new Map<string, number>()
  for (const t of tokens) m.set(t, (m.get(t) ?? 0) + 1)
  const n = tokens.length || 1
  for (const [k, v] of m) m.set(k, v / n)
  return m
}

function cosine(a: Map<string, number>, b: Map<string, number>): number {
  let dot = 0
  let na = 0
  let nb = 0
  for (const [k, va] of a) { const vb = b.get(k) ?? 0; dot += va * vb; na += va * va }
  for (const vb of b.values()) nb += vb * vb
  if (!na || !nb) return 0
  return dot / (Math.sqrt(na) * Math.sqrt(nb))
}

// Query rewriting — NER-aware expansion per query-and-conversation.md
export function rewriteQuery(q: string): string {
  const lower = q.toLowerCase()
  const expansions: string[] = []
  if (/(aizawl|mizoram)/.test(lower)) expansions.push('Mizoram Aizawl Ridge high susceptibility shale')
  if (/(imphal|manipur|churachand)/.test(lower)) expansions.push('Manipur Churachandpur Basin')
  if (/(shillong|meghalaya)/.test(lower)) expansions.push('Meghalaya Shillong Plateau')
  if (/(gangtok|sikkim)/.test(lower)) expansions.push('Sikkim Gangtok Valley')
  if (/(rain|rainfall|forecast|antecedent)/.test(lower)) expansions.push('M2 f12 a3 a7 Open-Meteo forecast rainfall mm')
  if (/(evacuation|warning|watch)/.test(lower)) expansions.push('NDMA threshold Watch Warning Evacuation severity')
  if (!expansions.length) return q
  return `${q} — expanded: ${expansions.join('; ')}`
}

export interface SearchOpts {
  topK: number
  enableReranker: boolean
  filters?: Record<string, string>
  collections?: RagCollection[]
}

export function hybridSearch(query: string, opts: SearchOpts): RagChunk[] {
  const qTokens = tf(tokenize(query))
  const qSet = new Set(tokenize(query))
  const candidates = CORPUS.filter((d) => !opts.collections?.length || opts.collections.includes(d.collection))
    .filter((d) => {
      if (!opts.filters) return true
      for (const [k, v] of Object.entries(opts.filters!)) {
        const mv = String(d.metadata[k] ?? '').toLowerCase()
        if (mv !== String(v).toLowerCase()) return false
      }
      return true
    })

  // Hybrid: dense (cosine) weighted 0.6 + sparse (keyword overlap) 0.4
  const scored: RagChunk[] = candidates.map((doc) => {
    const docTokens = tf(tokenize(`${doc.title} ${doc.content}`))
    const dense = cosine(qTokens, docTokens)
    const docSet = new Set(tokenize(`${doc.title} ${doc.content}`))
    let inter = 0
    for (const t of qSet) if (docSet.has(t)) inter++
    const sparse = qSet.size ? inter / qSet.size : 0
    const hybrid = 0.6 * dense + 0.4 * sparse
    // Simple reranker boost when collection matches query intent
    let rerank = 0
    if (opts.enableReranker) {
      rerank = doc.collection === 'geosentinel_guidelines' && /threshold|m1|m2|sop|ndma|gsi/i.test(query) ? 0.12 : 0
      if (/alert|evacuation|warning/i.test(query) && doc.collection === 'geosentinel_alerts') rerank += 0.10
      if (/report|citizen|triage/i.test(query) && doc.collection === 'geosentinel_reports') rerank += 0.10
    }
    const score = Math.min(1, hybrid + rerank)
    return { ...doc, chunkId: `${doc.id}#0`, score, rerankerScore: opts.enableReranker ? score : undefined }
  })

  scored.sort((a, b) => b.score - a.score)
  // Reranker threshold filtering (RERANKER_SCORE_THRESHOLD ~0.08 for demo)
  const filtered = opts.enableReranker ? scored.filter((c) => (c.rerankerScore ?? c.score) >= 0.08) : scored
  return filtered.slice(0, opts.topK)
}

export function getCollections(): { id: RagCollection; count: number; label: string }[] {
  const counts = new Map<RagCollection, number>()
  for (const d of CORPUS) counts.set(d.collection, (counts.get(d.collection) ?? 0) + 1)
  const labels: Record<RagCollection, string> = {
    geosentinel_guidelines: 'Guidelines & SOPs',
    geosentinel_alerts: 'Alerts',
    geosentinel_reports: 'Citizen Reports',
    geosentinel_capitals: 'Capitals & Districts',
    imd_nowcast: 'IMD Nowcast',
  }
  return Array.from(counts.entries()).map(([id, count]) => ({ id, count, label: labels[id] ?? id }))
}
