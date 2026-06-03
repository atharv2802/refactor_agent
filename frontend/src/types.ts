// Mirrors the backend Pydantic models (server/models.py). In a larger setup
// these would be generated from the FastAPI OpenAPI schema to stay in sync.

export interface ClaimInfo {
  claim_id: string;
  provider_npi: string;
  provider_tax_id: string;
  patient_member_id: string;
  patient_first_name: string;
  patient_last_name: string;
  patient_date_of_birth: string;
  date_of_service: string;
  billed_amount?: number | null;
}

export interface CallRequest {
  payer_name: string;
  payer_phone_number?: string | null;
  claims: ClaimInfo[];
}

export type ClaimStatus = "pending" | "adjusted" | "not_found" | "unresolved";
export type LineStatus = "paid" | "denied";

export interface ClaimLineResult {
  procedure_code?: string | null;
  line_number?: string | null;
  status: LineStatus;
  paid_amount?: number | null;
  billed_amount?: number | null;
  denial_reason_code?: string | null;
  denial_reason_description?: string | null;
}

export interface ClaimStatusResult {
  claim_id: string;
  status: ClaimStatus;
  pending_reason?: string | null;
  pending_timeline?: string | null;
  lines: ClaimLineResult[];
  total_paid_amount?: number | null;
  payment_date?: string | null;
  check_or_eft_number?: string | null;
  appeal_deadline?: string | null;
  status_details?: string | null;
  additional_info?: string | null;
  needs_human_review?: boolean;
  review_reasons?: string[];
  low_confidence_fields?: string[];
}

export interface TranscriptTurn {
  role: "agent" | "rep";
  text: string;
}

export interface CallResult {
  call_id: string;
  payer_name: string;
  call_timestamp: string;
  rep_name?: string | null;
  reference_number?: string | null;
  claims: ClaimStatusResult[];
  call_summary?: string | null;
  transcript: TranscriptTurn[];
}

export type CallPhase =
  | "idle"
  | "connecting"
  | "active"
  | "complete"
  | "error";

export interface TranscriptEntry {
  role: "agent" | "rep";
  text: string;
  ts: number;
}
