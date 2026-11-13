export const dynamic = "force-dynamic";

import Link from "next/link";
import { redirect } from "next/navigation";
import { sql } from "drizzle-orm";
import { auth } from "../../auth";
import { analystIdentity } from "../../lib/analyst-shortlist";
import { db } from "../../lib/db";
import Pagination from "../components/Pagination";
import OutreachShortlistControl from "./OutreachShortlistControl";

export default async function Outreach({ searchParams }: { searchParams: Promise<{ page?: string }> }) {
  const session = await auth();
  const analystId = analystIdentity(session);
  if (!analystId) redirect(`/login?callbackUrl=${encodeURIComponent("/outreach")}`);

  const params = await searchParams;
  const page = Math.max(1, Number(params.page) || 1);
  const pageSize = 25;
  const offset = (page - 1) * pageSize;
  const rows = await db.execute(sql`with active as (
      select dataset_version from dataset_versions order by published_at desc nulls last, dataset_version desc limit 1
    ), shortlist as (
      select f.firm_id, f.dataset_version, f.name, s.priority_category, s.acquisition_score,
        coalesce(o.status, 'NOT_RESEARCHED') as status, o.assigned_to, o.next_action, o.next_action_date
      from analyst_outreach_shortlists mine
      join active a on true
      join firms f on f.firm_id = mine.firm_id and f.dataset_version = a.dataset_version
      left join firm_scores s on s.firm_id = f.firm_id and s.dataset_version = f.dataset_version
      left join outreach_targets o on o.firm_id = f.firm_id and o.dataset_version = f.dataset_version
      where mine.analyst_id = ${analystId}
    )
    select *, count(*) over()::int as total_count from shortlist
    order by acquisition_score desc nulls last, firm_id limit ${pageSize} offset ${offset}`);
  const total = Number(rows.rows[0]?.total_count || 0);

  return <>
    <div className="top outreach-heading">
      <div><p className="eyebrow">Personal shortlist</p><h2>Outreach queue</h2><p className="muted">Only firms you add from Target Explorer appear here. Outreach preparation and activity tracking only; no messages are sent.</p></div>
      <Link className="button-link secondary" href="/targets">Open Target Explorer</Link>
    </div>
    {total === 0 ? <section className="panel outreach-empty">
      <h3>Your shortlist is empty</h3>
      <p className="muted">Add eligible firms to your personal shortlist from the Outreach column in Target Explorer.</p>
      <Link className="button-link" href="/targets">Browse firms</Link>
    </section> : <div className="panel table-wrap outreach-table">
      <table><thead><tr><th>Firm</th><th>Priority</th><th>Score</th><th>Shared outreach status</th><th>Owner</th><th>Next action</th><th>Date</th><th>My shortlist</th></tr></thead>
        <tbody>{rows.rows.map((row: any) => <tr key={row.firm_id}>
          <td><Link href={`/firms/${row.firm_id}`}>{row.name || row.firm_id}</Link><br/><small className="muted">CRD {row.firm_id}</small></td>
          <td>{row.priority_category?.replace("PRIORITY_", "") || "Unknown"}</td>
          <td>{row.acquisition_score == null ? "Unknown" : Number(row.acquisition_score).toFixed(1)}</td>
          <td><span className="badge">{row.status}</span></td>
          <td>{row.assigned_to || "Unassigned"}</td>
          <td>{row.next_action || "None"}</td>
          <td>{row.next_action_date || "None"}</td>
          <td><OutreachShortlistControl firmId={row.firm_id} initiallyShortlisted compact refreshOnRemove /></td>
        </tr>)}</tbody>
      </table>
      <Pagination path="/outreach" page={page} pageSize={pageSize} total={total} />
    </div>}
  </>;
}
