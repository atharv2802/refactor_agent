// Thin typed wrapper around the FastAPI endpoints. All paths are relative so the
// same code works behind the Vite dev proxy and when served from FastAPI.

import type { CallRequest, CallResult } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export async function getPublicKey(): Promise<string> {
  const data = await json<{ vapi_public_key: string }>(await fetch("/api/config"));
  return data.vapi_public_key;
}

export async function createCall(request: CallRequest): Promise<string> {
  const data = await json<{ call_id: string }>(
    await fetch("/api/claims", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }),
  );
  return data.call_id;
}

export async function getAssistant(callId: string): Promise<Record<string, unknown>> {
  return json(await fetch(`/api/assistant/${callId}`));
}

// Register Vapi's call id against our session so webhooks can resolve it.
export async function linkCall(callId: string, vapiCallId: string): Promise<void> {
  await json(
    await fetch(`/api/calls/${callId}/link`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vapi_call_id: vapiCallId }),
    }),
  );
}

export async function getResult(callId: string): Promise<CallResult | null> {
  const res = await fetch(`/api/results/${callId}`);
  if (res.status === 404) return null;
  return json<CallResult>(res);
}

export async function parse837(edi: string, payerName: string): Promise<CallRequest> {
  return json<CallRequest>(
    await fetch("/api/claims/837", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ edi, payer_name: payerName }),
    }),
  );
}

export async function loadSampleClaims(): Promise<CallRequest> {
  return json<CallRequest>(await fetch("/sample_claims.json"));
}
