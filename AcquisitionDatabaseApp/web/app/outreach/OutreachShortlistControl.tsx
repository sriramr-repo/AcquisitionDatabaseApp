"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type Props = {
  firmId: string;
  datasetVersion?: string;
  initiallyShortlisted: boolean;
  compact?: boolean;
  refreshOnRemove?: boolean;
};

export default function OutreachShortlistControl({
  firmId, datasetVersion, initiallyShortlisted, compact = false, refreshOnRemove = false,
}: Props) {
  const [shortlisted, setShortlisted] = useState(initiallyShortlisted);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();

  useEffect(() => setShortlisted(initiallyShortlisted), [initiallyShortlisted]);

  async function toggle() {
    if (saving || (!shortlisted && !datasetVersion)) return;
    setSaving(true);
    setError("");
    try {
      const response = await fetch(`/api/analyst-shortlist/${encodeURIComponent(firmId)}`, shortlisted
        ? { method: "DELETE" }
        : { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ datasetVersion }) });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(result?.error || "Unable to update your Outreach shortlist");
      setShortlisted(Boolean(result?.isShortlisted));
      if (refreshOnRemove && !result?.isShortlisted) router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to update your Outreach shortlist");
    } finally {
      setSaving(false);
    }
  }

  return <div className={`shortlist-control${compact ? " compact" : ""}`}>
    <button
      type="button"
      className={`shortlist-toggle${shortlisted ? " is-shortlisted" : ""}`}
      aria-pressed={shortlisted}
      aria-label={shortlisted ? `Remove ${firmId} from your Outreach shortlist` : `Add ${firmId} to your Outreach shortlist`}
      disabled={saving || (!shortlisted && !datasetVersion)}
      onClick={toggle}
    >{saving ? "Saving…" : compact ? "Remove" : shortlisted ? "Shortlisted" : "Add to Outreach"}</button>
    {error ? <small className="shortlist-error" role="alert">{error}</small> : null}
  </div>;
}
