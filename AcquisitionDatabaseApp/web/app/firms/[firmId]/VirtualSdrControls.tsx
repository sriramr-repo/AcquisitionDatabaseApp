"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type SdrProps = {
  firmId: string;
  datasetVersion: string;
  initialData: { runs: any[]; artifacts: any[]; reviews: any[]; qualityChecks: any[] };
  sources: Array<{ source_id: string; source_url?: string | null; source_title?: string | null }>;
};

const title = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, character => character.toUpperCase());

export function VirtualSdrControls({ firmId, datasetVersion, initialData, sources }: SdrProps) {
  const router = useRouter();
  const latestRun = initialData.runs[0] || null;
  const latestArtifact = initialData.artifacts.find((artifact: any) => artifact.artifact_id === latestRun?.latest_artifact_id) || initialData.artifacts[0] || null;
  const brief: any = latestArtifact?.content || null;
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [emailSubject, setEmailSubject] = useState(String(brief?.email_subject || ""));
  const [emailBody, setEmailBody] = useState(String(brief?.email_body || ""));
  const [callOpener, setCallOpener] = useState(String(brief?.call_opener || ""));
  const [notes, setNotes] = useState("");
  const [nextAction, setNextAction] = useState("Review approved CEO brief and prepare outreach");
  const [nextActionDate, setNextActionDate] = useState("");

  async function start() {
    setBusy(true); setMessage("Submitting…");
    const response = await fetch(`/api/virtual-sdr/${firmId}`, { method: "POST" });
    const payload = await response.json();
    setMessage(response.ok ? `Brief run ${payload.status}.` : payload.error_message || payload.error || "Unable to start brief");
    setBusy(false); router.refresh();
  }

  async function review(decision: "APPROVED" | "REJECTED" | "REVISION_REQUESTED") {
    if (!latestRun || !latestArtifact) return;
    setBusy(true); setMessage("Submitting review…");
    const edits: Record<string, string> = {};
    if (emailSubject !== String(brief?.email_subject || "")) edits.emailSubject = emailSubject;
    if (emailBody !== String(brief?.email_body || "")) edits.emailBody = emailBody;
    if (callOpener !== String(brief?.call_opener || "")) edits.callOpener = callOpener;
    const response = await fetch(`/api/virtual-sdr/runs/${latestRun.run_id}/review`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision,
        notes,
        edits,
      }),
    });
    const payload = await response.json();
    setMessage(response.ok ? "Review submitted. The durable workflow is resuming." : payload.error || "Unable to submit review");
    setBusy(false); router.refresh();
  }

  async function createNextAction() {
    setBusy(true);
    const response = await fetch(`/api/outreach/${firmId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ datasetVersion, nextAction, nextActionDate: nextActionDate || null }),
    });
    setMessage(response.ok ? "Next action saved without sending outreach." : "Unable to save next action");
    setBusy(false); router.refresh();
  }

  async function copyBrief() {
    if (!brief) return;
    const text = [
      brief.executive_summary?.text,
      brief.acquisition_fit_thesis?.text,
      `Email: ${emailSubject}\n${emailBody}`,
      `Call opener: ${callOpener}`,
      ...(brief.discovery_questions || []).map((question: string) => `• ${question}`),
    ].filter(Boolean).join("\n\n");
    try {
      await navigator.clipboard.writeText(text);
      setMessage("Brief copied.");
    } catch {
      setMessage("Clipboard access is unavailable; use Download JSON instead.");
    }
  }

  return <div className="panel sdr-panel">
    <div className="sdr-heading">
      <div><h3>Virtual SDR · CEO brief</h3><p className="muted">Meeting preparation only. Nothing is sent and only accepted evidence may support finalized claims.</p></div>
      <div className="agent-actions"><button type="button" disabled={busy} onClick={start}>Prepare CEO Brief</button><button type="button" className="secondary" disabled={busy} onClick={() => router.refresh()}>Refresh status</button></div>
    </div>
    {message ? <p className="muted" role="status">{message}</p> : null}
    {latestRun ? <div className="sdr-run-summary">
      <span className={`badge ${latestRun.status === "APPROVED" ? "good" : latestRun.status === "FAILED" || latestRun.status === "UNAVAILABLE" ? "warn" : ""}`}>{title(String(latestRun.status))}</span>
      <small className="muted">Workflow {latestRun.workflow_version} · {latestRun.model_provider}/{latestRun.model_name}</small>
      {latestRun.error_message ? <p className="muted"><b>Reason:</b> {latestRun.error_message}</p> : null}
    </div> : <p className="muted">No CEO briefing run exists for this firm.</p>}
    {brief ? <div className="sdr-brief">
      <section><h4>Executive summary</h4><p>{brief.executive_summary?.text}</p><SourceIds ids={brief.executive_summary?.source_ids} sources={sources} /></section>
      <section><h4>Acquisition-fit thesis</h4><p>{brief.acquisition_fit_thesis?.text}</p><SourceIds ids={brief.acquisition_fit_thesis?.source_ids} sources={sources} /></section>
      <section><h4>Verified decision makers</h4>{brief.decision_makers?.length ? brief.decision_makers.map((person: any, index: number) => <div key={`${person.name}-${index}`} className="brief-item"><b>{person.name}</b>{person.role ? ` · ${person.role}` : ""}<p>{person.rationale}</p><SourceIds ids={person.source_ids} sources={sources} /></div>) : <p className="muted">No verified decision maker available.</p>}</section>
      <section><h4>Talking points</h4>{brief.talking_points?.map((point: any, index: number) => <div key={index} className="brief-item"><p>{point.text}</p><SourceIds ids={point.source_ids} sources={sources} /></div>)}</section>
      <section><h4>Research gaps</h4>{brief.research_gaps?.length ? <ul>{brief.research_gaps.map((gap: string, index: number) => <li key={index}>{gap}</li>)}</ul> : <p className="muted">No material gaps reported.</p>}</section>
      <section className="sdr-editor"><h4>Email draft</h4><label>Subject<input value={emailSubject} maxLength={200} onChange={event => setEmailSubject(event.target.value)} /></label><label>Body<textarea rows={9} value={emailBody} maxLength={6000} onChange={event => setEmailBody(event.target.value)} /></label><h4>Call opener</h4><textarea rows={5} value={callOpener} maxLength={2000} onChange={event => setCallOpener(event.target.value)} /></section>
      <section><h4>Discovery questions</h4><ol>{brief.discovery_questions?.map((question: string, index: number) => <li key={index}>{question}</li>)}</ol></section>
      <section><h4>Likely objections</h4>{brief.likely_objections?.map((item: any, index: number) => <div className="brief-item" key={index}><b>{item.objection}</b><p>{item.response}</p></div>)}</section>
      <section><h4>Evidence set</h4><SourceIds ids={brief.source_ids} sources={sources} /><p className="muted">Confidence: {brief.confidence || "Unavailable"} · Quality gate: {latestArtifact.quality_status}</p></section>
      <div className="agent-actions"><button type="button" className="secondary" onClick={copyBrief}>Copy brief</button><a className="button-link" href={`/api/virtual-sdr/artifacts/${latestArtifact.artifact_id}/download`}>Download JSON</a></div>
      {latestRun.status === "AWAITING_APPROVAL" ? <section className="sdr-review"><h4>CEO review</h4><textarea rows={3} placeholder="Review notes or requested revisions" value={notes} onChange={event => setNotes(event.target.value)} /><div className="review-actions"><button type="button" disabled={busy} onClick={() => review("APPROVED")}>Approve</button><button type="button" disabled={busy} className="secondary" onClick={() => review("REVISION_REQUESTED")}>Request revision</button><button type="button" disabled={busy} className="secondary" onClick={() => review("REJECTED")}>Reject</button></div></section> : null}
      {latestRun.status === "APPROVED" ? <section className="sdr-next-action"><h4>Create next action</h4><input value={nextAction} onChange={event => setNextAction(event.target.value)} /><input type="date" value={nextActionDate} onChange={event => setNextActionDate(event.target.value)} /><button type="button" disabled={busy || !nextAction.trim()} onClick={createNextAction}>Save next action</button><p className="muted">This updates workflow preparation only; it does not send a message.</p></section> : null}
    </div> : null}
  </div>;
}

function SourceIds({ ids, sources }: { ids?: string[]; sources: SdrProps["sources"] }) {
  if (!ids?.length) return <small className="muted">No source IDs recorded.</small>;
  const lookup = new Map(sources.map(source => [source.source_id, source]));
  return <small className="source-id-list">Sources: {ids.map((id, index) => {
    const source = lookup.get(id);
    const separator = index ? " · " : "";
    return <span key={id}>{separator}{source?.source_url ? <a href={source.source_url} target="_blank" rel="noopener noreferrer">{source.source_title || id}</a> : id}</span>;
  })}</small>;
}
