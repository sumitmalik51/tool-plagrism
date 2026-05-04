export interface User {
  id: string;
  name: string;
  email: string;
  plan_type: string;
  email_verified?: boolean;
  trial_ends_at?: string;
  is_admin?: boolean;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface SignupRequest {
  name: string;
  email: string;
  password: string;
  referral_code?: string;
}

export interface AuthResponse {
  user: User;
  token: string;
}

export interface UsageResponse {
  plan_type: string;
  used_today: number;
  remaining: number | string;
  limit: number | string;
  word_quota: {
    used: number;
    limit: number | string;
    base_limit?: number | string;
    base_remaining?: number | string;
    topup_remaining?: number;
    remaining: number | string;
    resets_at?: string;
  };
}

export interface AnalysisResult {
  document_id: string;
  plagiarism_score: number;
  confidence_score: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  detected_sources: DetectedSource[];
  flagged_passages: FlaggedPassage[];
  ai_score?: number;
  grammar_score?: number;
  readability_score?: number;
  partial_result?: boolean;
  agents_failed?: string[];
  analysis_warnings?: string[];
  analysis_scope?: {
    original_chunks?: number;
    analyzed_chunks?: number;
    chunk_limit?: number;
    [key: string]: unknown;
  };
  empty_reason?: "no_matches" | "weak_only" | "no_corpus" | null;
}

export interface SourceTextBlock {
  text: string;
  word_count: number;
  similarity_score: number;
}

export interface DetectedSource {
  url: string;
  title: string;
  similarity: number;
  text_blocks: number;
  matched_words: number;
  source_type: string;
  matched_passages?: SourceTextBlock[];
}

export interface FlaggedPassage {
  text: string;
  similarity_score: number;
  source: string;
  reason?: string;
  match_type?: "exact" | "paraphrase" | "semantic" | null;
}

export interface ScanItem {
  document_id: string;
  filename?: string;
  plagiarism_score: number;
  ai_score?: number;
  risk_level: string;
  created_at: string;
  word_count?: number;
}

export interface Plan {
  id: string;
  name: string;
  price: number;
  period: string;
  features: string[];
}
