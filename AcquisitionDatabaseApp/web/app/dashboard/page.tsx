export const dynamic = "force-dynamic";

import Link from "next/link";
import { dashboardData } from "../../lib/queries";

const n = (value: any) => value == null ? "Unavailable" : Number(value).toLocaleString();

export default async function Dashboard() {
  const data = await dashboardData();
  const priorityAB = data.counts
    .filter((row: any) => ["PRIORITY_A", "PRIORITY_B"].includes(row.priority_category))
    .reduce((total: number, row: any) => total + Number(row.count), 0);

  return <>
    <div className="top overview-heading">
      <div><p className="eyebrow">Acquisition screening</p><h2>Overview</h2><p className="muted">Acquisition screening and sourcing operations</p></div>
      <span className="badge good">Protected</span>
    </div>
    <section className="grid overview-metrics" aria-label="Dataset summary">
      <div className="card"><div className="muted">Dataset</div><div className="metric metric-text">{data.dataset?.dataset_version || "Unavailable"}</div></div>
      <div className="card"><div className="muted">Registered firms</div><div className="metric">{n(data.dataset?.registered_firm_count ?? data.dataset?.gold_rows)}</div></div>
      <div className="card"><div className="muted">Acquisition targets</div><div className="metric">{n(data.dataset?.acquisition_target_count)}</div></div>
      <div className="card"><div className="muted">Priority A/B</div><div className="metric">{n(priorityAB)}</div></div>
      <div className="card"><div className="muted">Score version</div><div className="metric metric-text">{data.dataset?.score_version || "Unavailable"}</div></div>
    </section>
    <section className="panel overview-funnel">
      <div className="panel-heading"><div><p className="eyebrow">Portfolio breakdown</p><h3>Priority funnel</h3></div><Link href="/targets">Review firms →</Link></div>
      <div className="grid">{data.counts.map((row: any) => <div className="card" key={row.priority_category}><div className="muted">{row.priority_category}</div><div className="metric">{n(row.count)}</div></div>)}</div>
    </section>
    <section className="detail-grid overview-lower">
      <div className="panel"><p className="eyebrow">Research coverage</p><h3>Research status</h3>{data.research.map((row: any) => <div className="score-row" key={row.research_status}><span>{row.research_status}</span><b>{n(row.count)}</b></div>)}<p className="overview-link"><Link href="/research">Open research queue →</Link></p></div>
      <div className="panel overview-next"><p className="eyebrow">Workflow</p><h3>Next actions</h3><p className="muted">Use the Target Explorer to triage qualified prospects.</p><Link className="button-link" href="/targets">Open Target Explorer</Link></div>
    </section>
  </>;
}
