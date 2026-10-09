export type Capability =
  | "llm"
  | "image"
  | "video"
  | "tts"
  | "stt"
  | "music"
  | "search"
  | "publish";

export type Status =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "retry"
  | "cancelled"
  | "waiting_approval";

export type RunMode = "auto" | "manual" | "hybrid";

export type ProviderStatus =
  | "unknown"
  | "configured"
  | "checking"
  | "healthy"
  | "degraded"
  | "rate_limited"
  | "auth_error"
  | "model_error"
  | "network_error"
  | "unavailable"
  | "disabled"
  | "recovering"
  | "failed";

export type CircuitState = "closed" | "open" | "half_open";
export type AutoMode = "off" | "safe" | "aggressive";
export type KeyStatus = "active" | "cooldown" | "invalid" | "disabled";

export interface Project {
  id: string;
  name: string;
  description: string;
  niche: string;
  language: string;
  country: string;
  audience: string;
  style: string;
  default_duration: number;
  default_mode: RunMode;
  config: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProviderCatalogEntry {
  capability: Capability;
  provider_key: string;
  display_name: string;
  requires_api_key: boolean;
  default_endpoint: string;
  default_model: string;
  notes: string;
  param_schema: Record<string, unknown>;
}

export interface Provider {
  id: string;
  name: string;
  capability: Capability;
  provider: string;
  endpoint: string;
  model: string;
  params: Record<string, unknown>;
  priority: number;
  rate_limit: Record<string, unknown>;
  cost_config: Record<string, unknown>;
  enabled: boolean;
  is_fallback: boolean;
  api_key_masked: string;
  has_api_key: boolean;
  // --- Health / auto-recovery (additive) ---
  status: ProviderStatus;
  health_score: number;
  latency_ms: number;
  last_check_at: string | null;
  last_error: string;
  last_error_category: string;
  consecutive_failures: number;
  circuit_state: CircuitState;
  fallback_models: string[];
  auto_mode: AutoMode;
  recovery_enabled: boolean;
  keys_count: number;
  models_count: number;
}

export interface ProviderApiKey {
  id: string;
  label: string;
  priority: number;
  status: KeyStatus;
  usage_count: number;
  success_count: number;
  failure_count: number;
  health_score: number;
  avg_latency_ms: number;
  last_used_at: string | null;
  last_error: string;
  cooldown_until: string | null;
  api_key_masked: string;
}

export interface ProviderModel {
  id: string;
  name: string;
  capabilities: string[];
  context_length: number | null;
  deprecated: boolean;
  available: boolean;
}

export interface ProviderEvent {
  id: string;
  created_at: string;
  event_type: string;
  level: string;
  message: string;
  data: Record<string, unknown>;
  latency_ms: number | null;
}

export interface ProviderHealth {
  status: ProviderStatus;
  health_score: number;
  avg_latency_ms: number;
  last_latency_ms: number;
  p95_latency_ms: number;
  circuit_state: CircuitState;
  consecutive_failures: number;
  last_check_at: string | null;
  last_error: string;
  last_error_category: string;
}

export interface ProviderConfigHistoryEntry {
  id: string;
  created_at: string;
  reason: string;
  source: "manual" | "auto_fix" | "auto_recovery";
  snapshot: Record<string, unknown>;
}

export interface ProviderTestStep {
  name: string;
  ok: boolean;
  detail: string;
}

export interface ProviderTestResultV2 {
  ok: boolean;
  detail: string;
  steps: ProviderTestStep[];
  latency_ms: number | null;
}

export interface AutoFixResult {
  fixed: boolean;
  old_model: string;
  new_model: string | null;
  report: string;
  history_id: string | null;
}

export interface ProviderPreset {
  id: string;
  capability: Capability;
  provider: string;
  display_name: string;
  description: string;
  free: boolean;
  free_details: string;
  requires_api_key: boolean;
  default_endpoint: string;
  default_model: string;
  suggested_models: string[];
  signup_url: string;
  docs_url: string;
  api_key_label: string;
  setup_steps: string[];
  recommended: boolean;
}

export interface Video {
  id: string;
  project_id: string;
  title: string;
  description: string;
  idea: string;
  topic: string;
  status: Status;
  current_stage: string;
  mode: RunMode;
  config: Record<string, unknown>;
  stage_status: Record<string, string>;
  video_path: string;
  thumbnail_path: string;
  error: string;
  created_at: string;
  updated_at: string;
}

export interface Scene {
  id: string;
  index: number;
  duration: number;
  narration: string;
  dialogue: string;
  character_slugs: string[];
  location: string;
  visual_description: string;
  visual_prompt: string;
  video_prompt: string;
  camera: Record<string, unknown>;
  action: string;
  lighting: string;
  transition: string;
  subtitle: string;
  subtitle_position: string;
  image_path: string;
  clip_path: string;
  status: Status;
}

export interface VideoDetail extends Video {
  script: { id: string; content: string; structure: string } | null;
  scenes: Scene[];
}

export interface StageState {
  stage: string;
  status: Status;
}

export interface VideoProgress {
  id: string;
  status: Status;
  current_stage: string;
  stages: StageState[];
  error: string;
}

export interface LogEntry {
  id: string;
  created_at: string;
  level: string;
  agent: string;
  stage: string;
  message: string;
}

export interface DashboardSummary {
  videos_total: number;
  videos_by_status: { status: string; count: number }[];
  queue_depth: number;
  providers_enabled: number;
  projects_total: number;
  cost_today: number;
  cost_week: number;
  cost_month: number;
  cost_total: number;
}

export interface AgentConfig {
  id: string;
  project_id: string | null;
  agent_type: string;
  provider_config_id: string | null;
  model: string;
  temperature: number;
  max_tokens: number;
  system_prompt: string;
  params: Record<string, unknown>;
  enabled: boolean;
}

export interface Prompt {
  id: string;
  name: string;
  agent_type: string | null;
  project_id: string | null;
  content: string;
  version: number;
  is_active: boolean;
  is_default: boolean;
}

export interface Account {
  id: string;
  name: string;
  platform: string;
  params: Record<string, unknown>;
  enabled: boolean;
}
