export type Role = "admin" | "member";
export type ArticleGrade = 1 | 2 | 3 | 4;
export type GradeTierKey = "1" | "2" | "3" | "4";

export interface ArticleGradeActor {
  id: string;
  email: string;
}

export interface ArticleGradeCard {
  id: string;
  url: string;
  canonical_url?: string;
  title: string;
  thumbnail_url: string | null;
  grade: ArticleGrade | null;
  graded_by?: ArticleGradeActor | null;
  updated_by?: ArticleGradeActor | null;
  updated_at: string;
  revision: string;
}

export interface GradingBoard {
  ungraded: ArticleGradeCard[];
  tiers: Record<GradeTierKey, ArticleGradeCard[]>;
  revision: string;
}

export interface GradeArticleInput {
  grade: ArticleGrade | null;
  expected_revision?: string;
}

export type PipelineStatus =
  | "accepted"
  | "fetching"
  | "enriching"
  | "embedding"
  | "graphing"
  | "ready"
  | "failed";

export interface User {
  id: string;
  email: string;
  role: Role;
  active?: boolean;
  is_active?: boolean;
  created_at?: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token?: string;
  token_type?: string;
  user?: User;
}

export interface Operation {
  id: string;
  aggregate_id?: string;
  aggregate_type?: "signal" | "bundle";
  status: PipelineStatus | "pending" | "running" | "succeeded";
  stage?: PipelineStatus;
  detail?: string;
  error?: string;
  updated_at?: string;
}

export interface StageAttempt {
  id: string;
  stage: string;
  status: string;
  attempt: number;
  error?: string;
  retryable?: boolean;
  created_at?: string;
}

export interface SignalComment {
  id: string;
  signal_id: string;
  body: string;
  author: { id: string; email: string };
  created_at: string;
}

export interface Highlight {
  id: string;
  kind: "human" | "auto";
  start_offset: number;
  end_offset: number;
  text: string;
  active?: boolean;
  suppressed?: boolean;
  rationale?: string;
  created_at?: string;
}

export interface DocumentVersion {
  id: string;
  canonical_url?: string;
  title?: string;
  media_type?: string;
  content_hash?: string;
  normalized_text: string;
  retrieved_at?: string;
}

export interface ResearcherExtraction {
  id?: string;
  claims?: Array<{ text: string; start_offset?: number; end_offset?: number }>;
  entities?: Array<{ text: string; type?: string }>;
  numbers?: Array<{ text: string; value?: number; unit?: string }>;
  model_profile?: string;
  prompt_version?: string;
}

export interface NlpArtifact {
  entities?: Array<{ text: string; type?: string }>;
  dates?: Array<{ text: string; normalized?: string }>;
  numbers?: Array<{ text: string; value?: number; unit?: string }>;
  noun_phrases?: string[];
  sentence_count?: number;
}

export interface EvidenceSnapshot {
  id: string;
  revision?: number;
  recipe_version?: string;
  created_at?: string;
  prompt_hash?: string;
  config_hash?: string;
  input_highlight_ids?: string[];
}

export interface EmbeddingInfo {
  id: string;
  kind: "researcher" | "evidence" | "source_chunk" | "bundle";
  model_profile: string;
  dimensions: number;
  created_at?: string;
}

export interface SimilarityEdge {
  id?: string;
  signal_id?: string;
  target_signal_id?: string;
  target_id?: string;
  title?: string;
  score: number;
  edge_type?: string;
}

export interface SignalSummary {
  id: string;
  url: string;
  document_version_id?: string;
  canonical_url?: string;
  description_verbatim: string;
  status: PipelineStatus;
  title?: string;
  created_at?: string;
  updated_at?: string;
  archived_at?: string | null;
  operation_id?: string;
}

export interface SignalDetail extends SignalSummary {
  document_id?: string;
  document_version?: DocumentVersion;
  researcher_extraction?: ResearcherExtraction;
  nlp_artifact?: NlpArtifact;
  highlights?: Highlight[];
  comments?: SignalComment[];
  evidence_snapshots?: EvidenceSnapshot[];
  embeddings?: EmbeddingInfo[];
  neighbors?: SimilarityEdge[];
  stage_attempts?: StageAttempt[];
  failure?: { stage?: string; detail: string; retryable?: boolean };
}

export interface BundleItem {
  id?: string;
  position: number;
  url?: string;
  note?: string;
  signal_id?: string;
  signal?: SignalSummary;
}

export interface Bundle {
  id: string;
  thesis?: string;
  ordered: boolean;
  status: PipelineStatus;
  items: BundleItem[];
  evidence_snapshots?: EvidenceSnapshot[];
  embeddings?: EmbeddingInfo[];
  neighbors?: SimilarityEdge[];
  created_at?: string;
  operation_id?: string;
}

export interface Invitation {
  id: string;
  email: string;
  role: Role;
  status?: "pending" | "accepted" | "revoked" | "expired";
  expires_at: string;
  created_at?: string;
  invite_url?: string;
}

export interface AsyncAccepted {
  operation_id?: string;
  status_url?: string;
  aggregate_id?: string;
  id?: string;
  signal_id?: string;
  bundle_id?: string;
}

export interface PageResult<T> {
  items: T[];
  total?: number;
  next_cursor?: string;
}

export interface Problem {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
  errors?: Record<string, string[]>;
}
