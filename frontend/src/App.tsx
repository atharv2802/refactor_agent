import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./api";
import { useVapi } from "./useVapi";
import { ClaimsPanel } from "./components/ClaimsPanel";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { ResultsPanel } from "./components/ResultsPanel";
import type { CallPhase, CallResult, TranscriptEntry } from "./types";

const SAMPLE_837 = `ISA*00*          *00*          *ZZ*NORTHSTARMED   *ZZ*BLUESHIELDCA   *250110*1200*^*00501*000000001*0*P*:~
NM1*85*2*NORTHSTAR MEDICAL GROUP*****XX*1841293847~
REF*EI*954321987~
NM1*IL*1*GONZALEZ*MARIA****MI*BSC123456789~
DMG*D8*19850314*F~
CLM*CLM-2025-0001*1450.00***11:B:1*Y*A*Y*I~
DTP*472*D8*20250110~`;

export default function App() {
  const [claimsText, setClaimsText] = useState("");
  const [phase, setPhase] = useState<CallPhase>("idle");
  const [statusMessage, setStatusMessage] = useState<string | undefined>();
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [result, setResult] = useState<CallResult | null>(null);

  const publicKeyRef = useRef<string>("");
  const callIdRef = useRef<string>("");

  const setStatus = useCallback((p: CallPhase, msg?: string) => {
    setPhase(p);
    setStatusMessage(msg);
  }, []);

  const pollResult = useCallback(async () => {
    for (let i = 0; i < 8; i++) {
      const r = await api.getResult(callIdRef.current);
      if (r) {
        setResult(r);
        setStatus("complete", "Call complete");
        return;
      }
      await new Promise((res) => setTimeout(res, 1000));
    }
    setStatus("complete", "Call complete (results pending)");
  }, [setStatus]);

  const vapi = useVapi({
    onCallStart: () => setStatus("active", "In call — speak as the rep"),
    onCallEnd: () => {
      setStatus("complete", "Call complete — fetching results…");
      void pollResult();
    },
    onError: (msg) => setStatus("error", `Error: ${msg}`),
    onTranscript: (role, text) =>
      setTranscript((prev) => [...prev, { role, text, ts: Date.now() }]),
  });

  useEffect(() => {
    void (async () => {
      try {
        publicKeyRef.current = await api.getPublicKey();
        const sample = await api.loadSampleClaims().catch(() => null);
        if (sample) setClaimsText(JSON.stringify(sample, null, 2));
      } catch (e) {
        setStatus("error", `Init failed: ${(e as Error).message}`);
      }
    })();
  }, [setStatus]);

  const handleStart = useCallback(async () => {
    if (!publicKeyRef.current) {
      setStatus("error", "Vapi public key not configured on the server (.env).");
      return;
    }
    let request;
    try {
      request = JSON.parse(claimsText);
    } catch {
      setStatus("error", "Claims JSON is invalid.");
      return;
    }
    setTranscript([]);
    setResult(null);
    setStatus("connecting", "Creating session…");
    try {
      const callId = await api.createCall(request);
      callIdRef.current = callId;
      const assistant = await api.getAssistant(callId);
      setStatus("connecting", "Connecting to call…");
      const vapiCallId = await vapi.start(publicKeyRef.current, assistant);
      if (vapiCallId) {
        await api.linkCall(callId, vapiCallId).catch(() => undefined);
      }
    } catch (e) {
      setStatus("error", `Could not start: ${(e as Error).message}`);
    }
  }, [claimsText, setStatus, vapi]);

  const handleLoadSample = useCallback(async () => {
    const sample = await api.loadSampleClaims().catch(() => null);
    if (sample) setClaimsText(JSON.stringify(sample, null, 2));
  }, []);

  const handleParse837 = useCallback(async () => {
    setStatus("connecting", "Parsing 837…");
    try {
      const parsed = await api.parse837(SAMPLE_837, "Blue Shield of California");
      setClaimsText(JSON.stringify(parsed, null, 2));
      setStatus("idle", "837 parsed");
    } catch (e) {
      setStatus("error", `837 parse failed: ${(e as Error).message}`);
    }
  }, [setStatus]);

  return (
    <div className="flex h-full flex-col">
      <header className="bg-brand-700 px-6 py-4 text-white">
        <h1 className="text-lg font-semibold">Claim Status Voice Agent</h1>
        <p className="mt-0.5 text-sm text-brand-100">
          Speak as the payer rep. The agent calls to check claim status and extracts
          structured results live.
        </p>
      </header>
      <main className="mx-auto grid w-full max-w-[1400px] min-h-0 flex-1 grid-cols-1 gap-4 overflow-hidden p-4 lg:grid-cols-[380px_1fr_1fr]">
        <ClaimsPanel
          value={claimsText}
          onChange={setClaimsText}
          onLoadSample={handleLoadSample}
          onParse837={handleParse837}
          onStart={handleStart}
          onEnd={vapi.stop}
          phase={phase}
          statusMessage={statusMessage}
        />
        <TranscriptPanel entries={transcript} />
        <ResultsPanel result={result} />
      </main>
    </div>
  );
}
