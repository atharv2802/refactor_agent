import { useCallback, useEffect, useRef } from "react";
import Vapi from "@vapi-ai/web";

interface VapiCallbacks {
  onCallStart?: () => void;
  onCallEnd?: () => void;
  onError?: (message: string) => void;
  onTranscript?: (role: "agent" | "rep", text: string) => void;
}

// Encapsulates the Vapi Web SDK lifecycle behind a small, typed React hook so
// components never touch the SDK directly. The instance is created lazily once
// the public key is known.
export function useVapi(callbacks: VapiCallbacks) {
  const vapiRef = useRef<Vapi | null>(null);
  const cbRef = useRef(callbacks);
  cbRef.current = callbacks;

  const ensure = useCallback((publicKey: string) => {
    if (vapiRef.current) return vapiRef.current;
    const vapi = new Vapi(publicKey);

    vapi.on("call-start", () => cbRef.current.onCallStart?.());
    vapi.on("call-end", () => cbRef.current.onCallEnd?.());
    vapi.on("error", (e: unknown) => {
      const msg = e instanceof Error ? e.message : String((e as { message?: string })?.message ?? e);
      cbRef.current.onError?.(msg);
    });
    vapi.on("message", (msg: { type?: string; role?: string; transcriptType?: string; transcript?: string }) => {
      if (msg.type === "transcript" && msg.transcriptType === "final" && msg.transcript) {
        cbRef.current.onTranscript?.(msg.role === "assistant" ? "agent" : "rep", msg.transcript);
      }
    });

    vapiRef.current = vapi;
    return vapi;
  }, []);

  const start = useCallback(
    async (publicKey: string, assistant: Record<string, unknown>): Promise<string | null> => {
      const vapi = ensure(publicKey);
      const call = await vapi.start(assistant as never);
      return call?.id ?? null;
    },
    [ensure],
  );

  const stop = useCallback(() => {
    vapiRef.current?.stop();
  }, []);

  useEffect(() => {
    return () => {
      vapiRef.current?.stop();
    };
  }, []);

  return { start, stop };
}
