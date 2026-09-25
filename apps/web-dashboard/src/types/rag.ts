/**
 * RAG types — mirrors NVIDIA RAG Blueprint v2.6.0
 * References: docs/api-rag.md, references/configure/{search,agentic-rag,ingestion,query}.md
 * Adapted for GeoSentinel: collections over NER alerts/reports/capitals/guidelines.
 */

export type RagCollection = 'geosentinel_reports' | 'geosentinel_alerts' | 'geosentinel_capitals' | 'geosentinel_guidelines' | 'imd_nowcast'

export interface RagDocument {
  id: string
  collection: RagCollection
  title: string
  content: string
  metadata: Record<string, string | number>
  url?: string
}

export interface RagChunk extends RagDocument {
  chunkId: string
  score: number
  rerankerScore?: number
}

export interface RagQuery {
  text: string
  collectionNames?: RagCollection[]
  topK?: number // APP_RETRIEVER_TOPK, default 10
  enableReranker?: boolean
  enableQueryRewriting?: boolean
  agentic?: boolean
  filters?: Record<string, string>
  history?: Array<{ role: 'user' | 'assistant'; content: string }>
  enableWebSearch?: boolean
}

export interface RagCitation {
  documentId: string
  chunkId: string
  title: string
  score: number
  metadata: Record<string, string | number>
}

export interface RagResponse {
  answer: string
  citations: RagCitation[]
  rewrittenQuery?: string
  retrieval: RagChunk[]
  reasoningContent?: string
  agenticStages?: RagAgenticStage[]
  usage?: { promptTokens: number; completionTokens: number }
  provider?: 'remote' | 'local' | string
  model?: string
}

export interface RagAgenticStage {
  stage: 'planning' | 'query_rewriting' | 'retrieval' | 'reranking' | 'synthesis' | 'verification'
  eventType: 'stage_start' | 'stage_end' | 'content'
  content?: string
  durationMs?: number
}

export interface RagHealth {
  status: 'ok' | 'degraded' | 'down'
  deployment: 'self-hosted' | 'nvidia-hosted' | 'library' | 'not_running' | 'api-gateway-llm'
  configFile: string
  enabled: {
    agenticRag: boolean
    queryRewriting: boolean
    reranker: boolean
    hybridSearch: boolean
    guardrails: boolean
    vlm: boolean
  }
  services: Record<string, string>
}

export const DEFAULT_RAG_QUERY: RagQuery = {
  text: '',
  collectionNames: ['geosentinel_reports', 'geosentinel_alerts', 'geosentinel_guidelines'],
  topK: 6,
  enableReranker: true,
  enableQueryRewriting: true,
  agentic: true,
}
