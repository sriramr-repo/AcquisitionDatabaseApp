"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export function StartResearchAgent({ firmId }: { firmId: string }) {
  const [state, setState] = useState("");
  const router = useRouter();
  async function start() {
    setState("Queueing…");
    const response = await fetch(`/api/research-agent/${firmId}`, { method: "POST" });
    const payload = await response.json();
    setState(response.ok ? `Queued: ${payload.status}` : payload.error || "Unable to queue");
    if (response.ok) router.refresh();
  }
  return <div className="agent-actions"><button type="button" onClick={start}>Analyze captured evidence</button>{state && <small className="muted">{state}</small>}</div>;
}

export function ObservationReview({ observationId }: { observationId: string }) {
  const [busy, setBusy] = useState(false);
  const router = useRouter();
  async function review(status: string) {
    setBusy(true);
    await fetch(`/api/research-agent/observations/${observationId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    setBusy(false);
    router.refresh();
  }
  return <span className="review-actions">
    <button type="button" disabled={busy} onClick={()=>review("ACCEPTED")}>Accept</button>
    <button type="button" disabled={busy} className="secondary" onClick={()=>review("REJECTED")}>Reject</button>
    <button type="button" disabled={busy} className="secondary" onClick={()=>review("CONFLICTING")}>Conflict</button>
  </span>;
}
