export const dynamic = "force-dynamic";

import Link from "next/link";
import Pagination from "../components/Pagination";
import { iapdChangesData } from "../../lib/queries";

type ChangeParams = { type?:string; state?:string; priority?:string; aum?:string; conflicts?:string; page?:string };

const LABELS:Record<string,string> = {
  new_representative_count: "New representatives",
  representative_no_longer_present_count: "Representative no longer present in latest IAPD feed",
  employer_change_count: "Employer changes",
  registration_change_count: "Registration changes",
  disclosure_change_count: "Disclosure record changes",
  material_contact_change_count: "Material contact changes",
};
const COUNT_KEYS:Record<string,string> = {
  new_representative_count: "new_representatives",
  representative_no_longer_present_count: "disappeared_representatives",
  employer_change_count: "employer_changes",
  registration_change_count: "registration_changes",
  disclosure_change_count: "disclosure_changes",
  material_contact_change_count: "material_contact_changes",
};
const money = (value:any) => value == null ? "Unavailable" : `$${(Number(value) / 1e6).toFixed(1)}M`;
const priority = (value:any) => value ? String(value).replace("PRIORITY_", "") : "Unknown";

export default async function Changes({searchParams}:{searchParams:Promise<ChangeParams>}) {
  const p = await searchParams;
  const data = await iapdChangesData({changeType:p.type,state:p.state,priority:p.priority,aum:p.aum,conflicts:p.conflicts,page:Math.max(1,Number(p.page)||1)});
  const comparison:any = data.comparison;
  const counts = comparison?.counts || {};
  const paginationParams = {type:p.type,state:p.state,priority:p.priority,aum:p.aum,conflicts:p.conflicts};
  return <>
    <div className="top"><div><h2>IAPD change intelligence</h2><p className="muted">Factual representative deltas between {comparison?.previous_snapshot_date || "the baseline"} and {comparison?.current_snapshot_date || "the latest snapshot"}. Absence from the latest feed does not establish termination.</p></div></div>
    <div className="grid change-metrics">{Object.entries(LABELS).map(([column,label]) => <div className="card" key={column}><div className="muted">{label}</div><div className="metric">{Number(counts[COUNT_KEYS[column]] || 0).toLocaleString()}</div></div>)}</div>
    <form className="toolbar target-filters change-filters">
      <select name="type" defaultValue={p.type || ""}><option value="">All change types</option><option value="new_representatives">New representatives</option><option value="representative_no_longer_present">No longer present in latest feed</option><option value="employer_changes">Employer changes</option><option value="registration_changes">Registration changes</option><option value="disclosure_changes">Disclosure record changes</option><option value="material_contact_changes">Material contact changes</option></select>
      <select name="priority" defaultValue={p.priority || ""}><option value="">All priorities</option><option value="PRIORITY_A">A</option><option value="PRIORITY_B">B</option><option value="PRIORITY_C">C</option></select>
      <input name="state" defaultValue={p.state} placeholder="State" maxLength={2} aria-label="State" />
      <select name="aum" defaultValue={p.aum || ""}><option value="">All AUM</option><option value="under200">Under $200M</option></select>
      <label className="filter-check"><input type="checkbox" name="conflicts" value="1" defaultChecked={p.conflicts === "1"} /> Open conflicts only</label>
      <button>Apply</button><Link className="button-link secondary" href="/changes">Reset</Link>
    </form>
    <div className="panel table-wrap changes-table"><table><thead><tr><th>Firm</th><th>Priority</th><th>AUM</th><th>State</th><th>Representative changes</th><th>Review</th></tr></thead><tbody>
      {data.rows.map((row:any) => { const active=Object.entries(LABELS).filter(([column])=>Number(row[column]||0)>0); return <tr key={`${row.comparison_id}:${row.firm_id}`}><td><Link href={`/firms/${row.firm_id}#iapd-representatives`}>{row.name||row.firm_id}</Link><small className="flag-line muted">CRD {row.firm_id}</small></td><td>{priority(row.priority_category)}</td><td>{money(row.total_aum)}</td><td>{row.organization_state||"Unknown"}</td><td><ul className="compact-list">{active.map(([column,label])=><li key={column}><b>{Number(row[column]).toLocaleString()}</b> {label.toLowerCase()}</li>)}</ul></td><td>{row.has_open_conflict?<span className="badge warn">Open conflict</span>:<span className="badge good">No open conflict</span>}</td></tr>; })}
      {!data.rows.length?<tr><td colSpan={6}>No firms match these filters.</td></tr>:null}
    </tbody></table><Pagination path="/changes" page={data.page} pageSize={data.pageSize} total={data.total} params={paginationParams}/></div>
    <div className="panel"><h3>Interpretation guardrails</h3><ul className="compact-list">{(comparison?.interpretation_guardrails||[]).map((item:string)=><li key={item}>{item}</li>)}</ul></div>
    <div className="panel"><h3>Representative conflict review</h3>{data.reviews.length?data.reviews.map((review:any)=><div className="score-row" key={review.review_id}><span><b>CRD {review.individual_crd}</b><small className="score-meaning muted">{String(review.reason_code).replaceAll("_"," ")} · Updated {String(review.updated_at)}</small></span><span className={`badge ${review.status==="OPEN"?"warn":"good"}`}>{review.status}</span></div>):<p className="muted">No representative review records.</p>}</div>
  </>;
}
