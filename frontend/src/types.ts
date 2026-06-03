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

export type ClaimStatus =
  | "paid"
  | "denied"
  | "pending"
  | "in_review"
  | "not_found"
  | "other";

export interface ClaimStatusResult {
  claim_id: string;
  status: ClaimStatus;
  status_details?: string | null;
  paid_amount?: number | null;
  payment_date?: string | null;
  check_or_eft_number?: string | null;
  denial_reason_code?: string | null;
  denial_reason_description?: string | null;
  appeal_deadline?: string | null;
  additional_info?: string | null;
}

export interface CallResult {
  call_id: string;
  payer_name: string;
  call_timestamp: string;
  rep_name?: string | null;
  reference_number?: string | null;
  claims: ClaimStatusResult[];
  call_summary?: string | null;
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
