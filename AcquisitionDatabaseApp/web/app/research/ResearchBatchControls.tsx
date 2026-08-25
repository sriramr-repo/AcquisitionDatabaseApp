"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function ResearchBatchControls({ queueable }: { queueable: number }) {
  const [limit, setLimit] = useState(10);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function queueBatch() {
    setBusy(true);
    setMessage("Queueing a bounded Priority A batch…");
    const response = await fetch("/api/research-agent/batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ priority: "PRIORITY_A", limit }),
    });
    const payload = await response.json();
    if (response.ok) {
      setMessage(
        `Queued ${payload.queued} firm${payload.queued === 1 ? "" : "s"}; ${payload.remainingQueueable} remain queueable.`,
      );
      router.refresh();
    } else {
      setMessage(payload.error || "Unable to queue research batch");
    }
    setBusy(false);
  }

  return <div className="agent-actions">
    <label>
      Batch size{" "}
      <select value={limit} onChange={event => setLimit(Number(event.target.value))} disabled={busy}>
        <option value={5}>5</option>
        <option value={10}>10</option>
        <option value={25}>25</option>
      </select>
    </label>
    <button type="button" onClick={queueBatch} disabled={busy || queueable < 1}>
      {busy ? "Queueing…" : "Queue next Priority A firms"}
    </button>
    <small className="muted">{message || `${queueable} firms currently queueable`}</small>
  </div>;
}
