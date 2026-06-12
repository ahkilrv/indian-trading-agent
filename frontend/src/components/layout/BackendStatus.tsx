"use client";

import { useEffect, useState, useRef } from "react";
import { getBackendHealth } from "@/lib/api";

type Status = "checking" | "connected" | "disconnected";

export function BackendStatus() {
  const [status, setStatus] = useState<Status>("checking");
  const [latency, setLatency] = useState<number | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    let timeoutId: ReturnType<typeof setTimeout>;

    const check = async () => {
      const start = performance.now();
      try {
        const res = await getBackendHealth();
        if (!mountedRef.current) return;
        if (res.status === "ok") {
          setStatus("connected");
          setLatency(Math.round(performance.now() - start));
        } else {
          setStatus("disconnected");
          setLatency(null);
        }
      } catch {
        if (!mountedRef.current) return;
        setStatus("disconnected");
        setLatency(null);
      }
      if (mountedRef.current) {
        timeoutId = setTimeout(check, 30000);
      }
    };

    check();

    return () => {
      mountedRef.current = false;
      clearTimeout(timeoutId);
    };
  }, []);

  const dot = {
    checking: "bg-yellow-500",
    connected: "bg-green-500",
    disconnected: "bg-red-500",
  }[status];

  const label = {
    checking: "Checking...",
    connected: latency !== null ? `${latency}ms` : "Connected",
    disconnected: "Disconnected",
  }[status];

  return (
    <div className="flex items-center gap-1.5" title={`Backend ${status}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${dot} inline-block flex-shrink-0`} />
      <span className="text-[10px] text-muted-foreground">{label}</span>
    </div>
  );
}
