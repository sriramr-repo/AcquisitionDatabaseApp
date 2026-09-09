export const dynamic = "force-dynamic";

import { sql } from "drizzle-orm";
import { db } from "../../lib/db";
import { advCoverageData } from "../../lib/queries";

export default async function Operations() {
  const [runs,alerts,backups,adv,iapdRuns,iapdJobs,iapdReviews] = await Promise.all([
    db.execute(sql`select * from pipeline_runs order by started_at desc limit 25`),
    db.execute(sql`select * from alerts order by created_at desc limit 25`),
    db.execute(sql`select * from backup_metadata order by created_at desc limit 10`),
    advCoverageData(),
    db.execute(sql`select * from iapd_feed_runs order by started_at desc limit 10`),
    db.execute(sql`select status,count(*)::int count from iapd_live_jobs group by status order by status`),
    db.execute(sql`select reason_code,count(*)::int count from iapd_manual_review_queue where status='OPEN' group by reason_code order by reason_code`),
  ]);
  return <>
    <h2>Operations</h2>
    <div className="grid"><div className="card"><div className="muted">Recent runs</div><div className="metric">{runs.rows.length}</div></div><div className="card"><div className="muted">Alerts</div><div className="metric">{alerts.rows.length}</div></div><div className="card"><div className="muted">Backups</div><div className="metric">{backups.rows.length}</div></div><div className="card"><div className="muted">IAPD review items</div><div className="metric">{iapdReviews.rows.reduce((sum:number,row:any)=>sum+Number(row.count),0)}</div></div></div>
    <div className="detail-grid">
      <div className="panel"><h3>IAPD feed recovery</h3>{iapdRuns.rows.length ? iapdRuns.rows.map((run:any)=><div className="score-row" key={run.run_id}><span>{run.selected_date || run.requested_date}<small className="score-meaning">{run.source_url || "No valid feed selected"}</small></span><span className={`badge ${["success","fallback_success"].includes(run.status)?"good":"warn"}`}>{run.status}</span></div>) : <p className="muted">No recorded feed recovery runs.</p>}</div>
      <div className="panel"><h3>Live representative enrichment</h3>{iapdJobs.rows.length ? iapdJobs.rows.map((row:any)=><div className="score-row" key={row.status}><span>{row.status}</span><b>{row.count}</b></div>) : <p className="muted">No live enrichment jobs queued.</p>}<h4>Open conflicts</h4>{iapdReviews.rows.length ? iapdReviews.rows.map((row:any)=><div className="score-row" key={row.reason_code}><span>{String(row.reason_code).replaceAll("_"," ")}</span><b>{row.count}</b></div>) : <p className="muted">No open IAPD conflicts.</p>}</div>
    </div>
    <div className="panel"><h3>ADV custodian coverage</h3><p className="muted">Applicable means the structured SEC filing reports Schedule D 5.K.(3) custodian reporting as required.</p><div className="adv-fact-grid"><div><span>All firms</span><b>{adv.facts.total || 0}</b></div><div><span>Applicable</span><b>{adv.facts.applicable || 0}</b></div><div><span>Not required</span><b>{adv.facts.not_required || 0}</b></div><div><span>Requirement unavailable</span><b>{adv.facts.unavailable || 0}</b></div><div><span>Firms with custodian rows</span><b>{adv.custodians.firms || 0}</b></div><div><span>Custodian records</span><b>{adv.custodians.rows || 0}</b></div></div>{adv.jobs.map((job:any)=><div className="score-row" key={job.status}><span>{job.status}</span><b>{job.count}</b></div>)}</div>
    <div className="panel"><h3>Production runs</h3>{runs.rows.map((r:any)=><div className="score-row" key={r.run_id}><span>{r.dataset_version || "Unknown"} · {r.status}</span><span>{r.started_at?.toString()}</span></div>)}</div>
  </>;
}
