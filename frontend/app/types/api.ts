// Mirrors backend/app/schemas/*.py — keep in sync when those change.

export interface Maintainer {
  github: string | null
  email: string | null
}

export interface RegisterRef {
  id: string
  name: string
  register_url: string
}

export interface OrgSummary {
  id: string
  name: string
  description: string | null
  url: string | null
}

export interface OrgDetail extends OrgSummary {
  maintainers: Maintainer[]
  registers: RegisterRef[]
}

export interface RegisterDepEdge {
  id: string
  kind: string
}

export interface RegisterSummary {
  id: string
  org_id: string
  name: string
  register_url: string
  viewer_url: string | null
  description: string | null
}

export interface RegisterDetail extends RegisterSummary {
  modified: string | null
  last_crawled_at: string | null
  last_crawl_status: string | null
  last_error: string | null
  bblocks: BblockSummary[]
  depends_on: RegisterDepEdge[]
  dependents: RegisterDepEdge[]
}

export interface DepEdge {
  id: string
  kind: string
}

export interface BblockSummary {
  id: string
  register_id: string
  name: string
  abstract: string | null
  status: string | null
  item_class: string | null
  version: string | null
  tags: string[]
  has_schema: boolean
  has_ld_context: boolean
  has_shacl_shapes: boolean
  matched_chunk_types: string[] | null
}

export interface BblockDetail extends BblockSummary {
  date_time_addition: string | null
  date_of_last_change: string | null
  schema_urls: Record<string, string>
  ld_context_url: string | null
  shacl_shapes_urls: string[]
  sources: Array<{ title?: string, link?: string }>
  depends_on: DepEdge[]
  dependents: DepEdge[]
}

export interface BblockListResponse {
  numberMatched: number
  numberReturned: number
  items: BblockSummary[]
}

export interface BblockListParams {
  q?: string
  item_class?: string
  status?: string
  register?: string
  org?: string
  limit?: number
  offset?: number
}
