export interface ArticleSummary {
  id: number;
  feed_id: number;
  feed_title: string | null;
  url: string;
  title: string | null;
  author: string | null;
  published_at: string | null;
  overview: string | null;
  severity_hint: string | null;
  is_read: boolean;
  is_saved: boolean;
  story_cluster_id: number | null;
  tier: string;
}

export interface ConstellationItem {
  cluster_id: number;
  member_count: number;
  representative: ArticleSummary;
  other_sources: ArticleSummary[];
  shared_keywords?: string[];
  avg_similarity?: number | null;
}

export interface StreamPage {
  view: "flat" | "grouped";
  items: ArticleSummary[] | ConstellationItem[];
  next_cursor: string | null;
}

export interface ArticleDetail extends ArticleSummary {
  enriched: any | null;
}

export interface RelatedArticle {
  id: number;
  feed_title: string | null;
  url: string;
  title: string | null;
  published_at: string | null;
  overview: string | null;
  similarity: number;
  shared_tokens: string[];
}

export interface RelatedResponse {
  article_id: number;
  cluster_id: number | null;
  members: RelatedArticle[];
}

export interface FeedOut {
  id: number;
  url: string;
  title: string | null;
  site_url: string | null;
  folder: string;
  custom_title: string | null;
  last_polled_at: string | null;
  last_status: string | null;
  error_count: number;
  is_active?: number;
}

export interface FolderInfo {
  name: string;
  feed_count: number;
}

export interface FeedHealth {
  id: number;
  url: string;
  title: string | null;
  last_polled_at: string | null;
  last_status: string | null;
  error_count: number;
  article_count: number;
  pending_count: number;
  enriched_count: number;
  failed_count: number;
}

export interface WatchOut {
  id: number;
  name: string;
  query: any;
  notify: boolean;
  created_at: string;
}

export interface SearchHit {
  id: number;
  feed_id: number;
  feed_title: string | null;
  url: string;
  title: string | null;
  published_at: string | null;
  overview: string | null;
  severity_hint: string | null;
  story_cluster_id: number | null;
  tier: string;
}

export interface SearchResponse {
  hits: SearchHit[];
  count: number;
  next_cursor?: string | null;
}

export interface NotificationItem {
  id: number;
  watch_id: number | null;
  watch_name: string | null;
  article_id: number | null;
  title: string;
  body: string | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationList {
  items: NotificationItem[];
  unread_count: number;
}

export interface MetricsOverview {
  article_count: number;
  enriched_count: number;
  pending_count: number;
  cluster_count: number;
  feed_count: number;
  saved_count: number;
  days: number;
}

export interface EntityCount {
  type: string;
  name: string;
  display_name: string;
  count: number;
}

export interface TimeBucket {
  bucket: string;
  count: number;
}

export interface SeverityBreakdown {
  severity: string | null;
  count: number;
}

export interface Me {
  id: number;
  username: string;
  is_admin: boolean;
}

export interface AuthResponse {
  access_token: string;
  user_id: number;
  username: string;
  is_admin: boolean;
}

export const ENTITY_TYPES = [
  { value: "threat_actor", label: "Threat Actor" },
  { value: "malware", label: "Malware" },
  { value: "tool", label: "Tool" },
  { value: "vendor", label: "Vendor" },
  { value: "company", label: "Company" },
  { value: "product", label: "Product" },
  { value: "cve", label: "CVE" },
  { value: "mitre_group", label: "MITRE Group" },
  { value: "mitre_software", label: "MITRE Software" },
  { value: "ttp_mitre", label: "MITRE Technique" },
  { value: "mitre_tactic", label: "MITRE Tactic" },
  { value: "sector", label: "Sector" },
  { value: "country", label: "Country" },
] as const;

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------
export interface ReportListItem {
  id: number;
  name: string;
  audience: string;
  structure_kind: string;
  length_target: string;
  article_count: number;
  status: string;
  cost_usd: number | null;
  model: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ReportDetail extends ReportListItem {
  body_md: string;
  request: any;
  article_ids: number[];
  error: string | null;
}

export interface ReportPreview {
  article_count: number;        // true total in scope (uncapped)
  used_count: number;           // min(article_count, cap) -- what report actually consumes
  cap: number;                  // server-side MAX_ARTICLES
  capped: boolean;              // true iff article_count > cap
  sample: {
    id: number;
    title: string | null;
    url: string;
    feed_title: string | null;
    published_at: string | null;
    severity_hint: string | null;
  }[];
  estimated_cost_usd: number;
}

export interface ReportRequest {
  name: string;
  keywords: string[];
  since_days: number;
  feed_ids?: number[] | null;
  any_of: Record<string, string[]>;
  all_of: Record<string, string[]>;
  has_entity_types: string[];
  structure_kind: "BLUF" | "custom";
  sections: string[];
  audience: "executive" | "technical" | "both";
  length: "short" | "medium" | "long";
  scope_note: string;
}

export const HAS_METADATA_OPTIONS = [
  { value: "threat_actor", label: "Threat Actors" },
  { value: "malware", label: "Malware" },
  { value: "cve", label: "CVEs" },
  { value: "ttp_mitre", label: "MITRE Techniques" },
  { value: "mitre_tactic", label: "MITRE Tactics" },
  { value: "mitre_group", label: "MITRE Groups" },
  { value: "mitre_software", label: "MITRE Software" },
  { value: "sector", label: "Sectors" },
  { value: "country", label: "Countries" },
  { value: "vendor", label: "Vendors" },
] as const;
