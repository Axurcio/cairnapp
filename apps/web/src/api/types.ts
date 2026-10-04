// Mirrors the API models in cairn/api/schemas.py (only the fields the site uses).

export type Role = "platform_admin" | "tenant_admin" | "facilitator" | "participant";

export type ConsentScope = "conversation" | "context_projection" | "evidence" | "reporting";

export type JourneyStatus = "active" | "paused" | "processing_restricted" | "closed";

export interface Account {
  id: string;
  email: string;
  display_name: string;
  actor_id: string;
  roles: Role[];
  tenant_id: string | null;
  tenant_name: string | null;
  participant_id: string | null;
}

export interface Session {
  account: Account;
  csrf_token: string;
  expires_at: string;
}

export interface Journey {
  id: string;
  participant_id: string;
  title: string;
  domain_pack: string;
  domain_pack_version: string;
  status: JourneyStatus;
  is_synthetic: boolean;
  started_at: string;
}

export interface JourneySummary extends Journey {
  participant_display_name: string | null;
  domain_pack_name: string | null;
}

export interface TimelineEntry {
  event_id: string;
  event_type: string;
  actor_type: string;
  occurred_at: string;
  source: string;
  text: string | null;
  evidence_refs: string[];
  details: Record<string, unknown>;
}

export interface NextAction {
  id: string;
  action_type: string;
  status: string;
  reason: string;
  question_id: string | null;
  field: string | null;
  policy_id: string | null;
  policy_version: string | null;
  domain_pack: string | null;
  domain_pack_version: string | null;
  occurred_at: string;
}

export interface Observation {
  id: string;
  observation_type: string;
  fields: Record<string, unknown>;
  status: string;
  confirmed: boolean;
  confidence: number | null;
  occurred_at: string;
  updated_at: string;
}

export interface MessageResponse {
  journey_id: string;
  participant_event_id: string;
  assistant_event_id: string;
  response: { text: string; renderer: string };
  next_action: NextAction;
  observation: Observation | null;
}

export interface ReportStatement {
  text: string;
  observation_id: string | null;
}

export interface Report {
  id: string;
  template_id: string;
  generated_at: string;
  disclaimer: string;
  sections: { title: string; statements: ReportStatement[] }[];
}

export interface Evidence {
  id: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
}
