/**
 * Assistant LLM service — talks to the universal assistant at POST /api/v1/assistant/query.
 * The endpoint is OpenAI-compatible on the server (Groq/OpenAI/Together/Ollama/NVIDIA)
 * and always grounds answers in live platform context + optional RAG chunks.
 * Falls back to local synthesis when the backend is unreachable.
 */

const API_BASE = '/api/v1'

export interface AssistantHistoryTurn {
  role: 'user' | 'assistant'
  content: string
}

export interface AssistantQueryRequest {
  query: string
  history?: AssistantHistoryTurn[]
  // Optional RAG retrieval already performed client-side — server injects as cited context
  rag_context?: Array<{ id: string; title: string; content: string; score?: number; chunkId?: string; collection?: string }>
  collection_names?: string[]
  top_k?: number
  context?: Record<string, unknown>
  enable_web_search?: boolean
}

export interface AssistantQueryResponse {
  answer: string
  model: string
  provider: 'remote' | 'local'
  latency_ms: number
}

export async function assistantQuery(req: AssistantQueryRequest): Promise<AssistantQueryResponse | null> {
  try {
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), 19000)
    const res = await fetch(`${API_BASE}/assistant/query`, {
      method: 'POST',
      signal: ctrl.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: req.query,
        history: req.history ?? [],
        rag_context: req.rag_context,
        collection_names: req.collection_names,
        top_k: req.top_k,
        context: req.context,
        enable_web_search: req.enable_web_search ?? true,
      }),
    })
    clearTimeout(t)
    if (!res.ok) return null
    const j = (await res.json()) as AssistantQueryResponse
    if (typeof j.answer === 'string' && j.answer.trim()) return j
    return null
  } catch {
    return null
  }
}

export interface GuidelineDoc {
  id: string
  collection: string
  title: string
  content: string
  metadata?: Record<string, string | number>
}

export async function fetchGuidelines(): Promise<GuidelineDoc[] | null> {
  try {
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), 2000)
    const res = await fetch(`${API_BASE}/knowledge/guidelines`, { signal: ctrl.signal })
    clearTimeout(t)
    if (!res.ok) return null
    const j = (await res.json()) as { items?: GuidelineDoc[] }
    if (j.items && Array.isArray(j.items)) return j.items
    return null
  } catch {
    return null
  }
}
