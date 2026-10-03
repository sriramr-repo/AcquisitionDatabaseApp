"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { sellerIntentDefinitions, sellerIntentSourceTypes, sellerIntentStatuses } from "../../../lib/seller-intent";

export function AdvRefresh({ firmId }: { firmId: string }) {
  const [message, setMessage] = useState(""); const router = useRouter();
  async function refresh() { setMessage("Queueing…"); const response = await fetch(`/api/adv/${firmId}/refresh`, { method: "POST" }); const body = await response.json(); setMessage(response.ok ? `Refresh ${body.status.toLowerCase()}` : body.error); if (response.ok) router.refresh(); }
  return <div className="agent-actions"><button type="button" onClick={refresh}>Refresh current ADV</button>{message ? <small className="muted">{message}</small> : null}</div>;
}

export function SellerIntentControls({ firmId, evidence }: { firmId: string; evidence: any[] }) {
  const router = useRouter(); const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  async function submit(formData: FormData) {
    setBusy(true); setMessage("");
    const payload = Object.fromEntries(formData.entries());
    const response = await fetch(`/api/seller-intent/${firmId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const body = await response.json(); setMessage(response.ok ? "Evidence proposed for review." : body.error); setBusy(false); if (response.ok) router.refresh();
  }
  async function review(decision: string, evidenceId?: string) { setBusy(true); const response = await fetch(`/api/seller-intent/${firmId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, evidenceId }) }); const body = await response.json(); setMessage(response.ok ? "Seller intent updated." : body.error); setBusy(false); if (response.ok) router.refresh(); }
  return <>
    <details className="intent-entry"><summary>Add seller-intent evidence</summary><form action={submit}>
      <label>Proposed status<select name="proposedStatus" required>{sellerIntentStatuses.filter(status=>!["UNKNOWN","STALE"].includes(status)).map(status=><option key={status} value={status}>{status}</option>)}</select></label>
      <label>Evidence source<select name="sourceType" required>{sellerIntentSourceTypes.map(source=><option key={source} value={source}>{source.replaceAll("_"," ")}</option>)}</select></label>
      <label>Evidence date<input name="evidenceDate" type="date" required /></label>
      <label>Direct excerpt or factual note<textarea name="evidenceExcerpt" rows={3} required /></label>
      <label>Source URL (optional)<input name="sourceUrl" type="url" /></label>
      <button disabled={busy}>Propose evidence</button>
    </form></details>
    {evidence.map(item=><div className="observation" key={item.evidence_id}><b>{item.proposed_status}</b> · {item.review_status}<blockquote>{item.evidence_excerpt}</blockquote><small className="muted">{item.source_type.replaceAll("_"," ")} · {String(item.evidence_date)} · {item.confidence}</small>{item.review_status === "PROPOSED" ? <span className="review-actions"><button disabled={busy} onClick={()=>review("ACCEPT",item.evidence_id)}>Confirm</button><button className="secondary" disabled={busy} onClick={()=>review("REJECT",item.evidence_id)}>Reject</button></span> : null}</div>)}
    <div className="intent-definitions">{Object.entries(sellerIntentDefinitions).map(([status, definition])=><div key={status}><b>{status}</b><span>{definition}</span></div>)}</div>
    <div className="agent-actions"><button className="secondary" disabled={busy} onClick={()=>review("MARK_STALE")}>Mark current status stale</button>{message ? <small className="muted">{message}</small> : null}</div>
  </>;
}
