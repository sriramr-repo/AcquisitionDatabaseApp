export const dynamic = "force-dynamic";

import { sql } from "drizzle-orm";
import { db } from "../../lib/db";
import { researchAgentProgress } from "../../lib/research-agent";
import Pagination from "../components/Pagination";
import ResearchBatchControls from "./ResearchBatchControls";

const count = (value: unknown) => Number(value || 0).toLocaleString();

export default async function Research({ searchParams }: { searchParams: Promise<{page?: string}> }) {
  const params = await searchParams;
  const page = Math.max(1, Number(params.page) || 1);
  const pageSize = 25;
  const offset = (page - 1) * pageSize;
  const [progress, rows] = await Promise.all([
    researchAgentProgress(),
    db.execute(sql`with latest_dataset as (
        select dataset_version from dataset_versions order by published_at desc limit 1
      ), latest_jobs as (
        select distinct on (j.firm_id,j.dataset_version) j.firm_id,j.dataset_version,j.status,j.attempt_count,j.max_attempts,j.updated_at
        from research_agent_jobs j join latest_dataset d using(dataset_version)
        where j.prompt_version='scm-research-prompt-v7' and j.extraction_version='scm-research-extraction-v7'
        order by j.firm_id,j.dataset_version,j.created_at desc
      ), sources as (
        select s.firm_id,s.dataset_version,count(distinct s.source_id)::int as source_count,
          count(distinct c.capture_id) filter(where c.content is not null and c.content<>'')::int as capture_count
        from research_sources s left join research_evidence_captures c using(source_id)
        group by s.firm_id,s.dataset_version
      ), observations as (
        select o.firm_id,o.dataset_version,count(*) filter(where o.review_status='PROPOSED')::int as proposed_count,
          count(*) filter(where o.review_status='CONFLICTING')::int as conflict_count
        from research_observations o join latest_dataset d using(dataset_version)
        group by o.firm_id,o.dataset_version
      ) select f.firm_id,f.name,s.acquisition_score,
        coalesce(r.research_status,'NOT_STARTED') as research_status,r.research_owner,
        coalesce(src.source_count,0)::int as source_count,coalesce(src.capture_count,0)::int as capture_count,
        j.status as agent_status,j.attempt_count,j.max_attempts,
        coalesce(o.proposed_count,0)::int as proposed_count,coalesce(o.conflict_count,0)::int as conflict_count,
        count(*) over()::int as total_count
      from firms f join firm_scores s using(firm_id,dataset_version) join latest_dataset d using(dataset_version)
      left join firm_research r using(firm_id,dataset_version)
      left join sources src using(firm_id,dataset_version)
      left join latest_jobs j using(firm_id,dataset_version)
      left join observations o using(firm_id,dataset_version)
      where s.priority_category='PRIORITY_A'
      order by case coalesce(j.status,'NOT_QUEUED')
        when 'REVIEW_REQUIRED' then 1 when 'RUNNING' then 2 when 'QUEUED' then 3
        when 'FAILED' then 4 when 'UNAVAILABLE' then 5 else 6 end,
        s.acquisition_score desc nulls last,f.firm_id
      limit ${pageSize} offset ${offset}`),
  ]);
  const total = Number(rows.rows[0]?.total_count || progress.total_firms || 0);
  return <>
    <div className="top"><div><h2>Priority A research operations</h2><p className="muted">Bounded evidence extraction with mandatory analyst review.</p></div><span className="badge good">Review-gated</span></div>
    <div className="grid">
      <div className="card"><div className="muted">Priority A firms</div><div className="metric">{count(progress.total_firms)}</div></div>
      <div className="card"><div className="muted">Evidence available</div><div className="metric">{count(progress.firms_with_evidence)}</div></div>
      <div className="card"><div className="muted">Queued / running</div><div className="metric">{count(Number(progress.queued || 0) + Number(progress.running || 0))}</div></div>
      <div className="card"><div className="muted">Awaiting review</div><div className="metric">{count(progress.review_required)}</div></div>
    </div>
    <div className="panel">
      <h3>Controlled batch queue</h3>
      <p className="muted">Only firms with captured evidence are selected. Repeated requests are idempotent, and no observation is accepted automatically.</p>
      <ResearchBatchControls queueable={Number(progress.queueable || 0)} />
      <div className="grid research-progress-grid">
        <div><b>{count(progress.firms_without_evidence)}</b><small className="muted">No captured evidence</small></div>
        <div><b>{count(progress.completed)}</b><small className="muted">Completed, no proposals</small></div>
        <div><b>{count(progress.failed)}</b><small className="muted">Failed</small></div>
        <div><b>{count(progress.unavailable)}</b><small className="muted">Provider unavailable</small></div>
        <div><b>{count(progress.proposed_observations)}</b><small className="muted">Proposed observations</small></div>
        <div><b>{count(progress.conflicting_observations)}</b><small className="muted">Conflicts</small></div>
      </div>
    </div>
    <div className="panel table-wrap research-table">
      <table><thead><tr><th>Firm</th><th>Score</th><th>Research</th><th>Evidence</th><th>Agent</th><th>Attempt</th><th>Proposals</th><th>Conflicts</th></tr></thead>
        <tbody>{rows.rows.map((row:any) => <tr key={`${row.firm_id}-research`}>
          <td><a href={`/firms/${row.firm_id}`}>{row.name || row.firm_id}</a><br/><small className="muted">CRD {row.firm_id}</small></td>
          <td>{row.acquisition_score == null ? "Unknown" : Number(row.acquisition_score).toFixed(1)}</td>
          <td>{row.research_status}</td>
          <td>{row.capture_count} captures<br/><small className="muted">{row.source_count} sources</small></td>
          <td><span className={`badge ${row.agent_status === "REVIEW_REQUIRED" ? "warn" : ""}`}>{row.agent_status || "NOT_QUEUED"}</span></td>
          <td>{row.attempt_count == null ? "—" : `${row.attempt_count}/${row.max_attempts}`}</td><td>{row.proposed_count}</td><td>{row.conflict_count}</td>
        </tr>)}</tbody>
      </table>
      <Pagination path="/research" page={page} pageSize={pageSize} total={total} />
    </div>
  </>;
}
