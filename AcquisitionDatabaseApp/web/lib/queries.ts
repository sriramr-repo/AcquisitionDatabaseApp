import { sql } from "drizzle-orm";
import { db } from "./db";

export async function dashboardData(): Promise<any>{
  const [dataset, counts, research, outreach] = await Promise.all([
    db.execute(sql`select * from dataset_versions order by dataset_version desc limit 1`),
    db.execute(sql`select priority_category, count(*)::int as count from firm_scores group by priority_category order by priority_category`),
    db.execute(sql`select research_status, count(*)::int as count from firm_research group by research_status order by research_status`),
    db.execute(sql`select status, count(*)::int as count from outreach_targets group by status order by status`),
  ]); return {dataset: dataset.rows[0] || null, counts: counts.rows, research: research.rows, outreach: outreach.rows};
}
export async function targetData(params: {search?:string; priority?:string; page?:number; pageSize?:number}): Promise<any>{
  const search = params.search ? `%${params.search}%` : null; const priority = params.priority || null;
  const page = Math.max(1, params.page || 1); const size = Math.min(100, Math.max(10, params.pageSize || 25)); const offset=(page-1)*size;
  const rows = await db.execute(sql`select f.firm_id, f.dataset_version, f.name, f.organization_state, s.priority_category, s.acquisition_score, s.review_required, x.total_aum, x.discretionary_aum, x.individual_hnw_share, x.total_account_count, x.average_account_size, x.employee_count, x.advisory_employee_count, r.research_status, o.status as outreach_status
    from firms f join firm_scores s using (firm_id,dataset_version) left join firm_facts x using (firm_id,dataset_version) left join firm_research r using (firm_id,dataset_version) left join outreach_targets o using (firm_id,dataset_version)
    where (${search}::text is null or f.name ilike ${search} or f.firm_id::text ilike ${search}) and (${priority}::text is null or s.priority_category=${priority}) order by s.acquisition_score desc nulls last, f.firm_id limit ${size} offset ${offset}`);
  const total = await db.execute(sql`select count(*)::int as count from firms f join firm_scores s using (firm_id,dataset_version) where (${search}::text is null or f.name ilike ${search} or f.firm_id::text ilike ${search}) and (${priority}::text is null or s.priority_category=${priority})`);
  return {rows: rows.rows, total: Number(total.rows[0]?.count || 0), page, pageSize:size};
}
export async function firmData(firmId:string): Promise<any>{
  const [firm,facts,scores,research,sources,contacts,outreach,activities] = await Promise.all([
    db.execute(sql`select * from firms where firm_id=${firmId} order by dataset_version desc limit 1`),
    db.execute(sql`select x.* from firm_facts x where firm_id=${firmId} order by dataset_version desc limit 1`),
    db.execute(sql`select s.* from firm_scores s where firm_id=${firmId} order by dataset_version desc limit 1`),
    db.execute(sql`select r.* from firm_research r where firm_id=${firmId} order by dataset_version desc limit 1`),
    db.execute(sql`select * from research_sources where firm_id=${firmId} order by accessed_at desc nulls last`),
    db.execute(sql`select * from contacts where firm_id=${firmId} order by contact_name`),
    db.execute(sql`select * from outreach_targets where firm_id=${firmId} order by dataset_version desc limit 1`),
    db.execute(sql`select * from outreach_activities where firm_id=${firmId} order by occurred_at desc`),
  ]); return {firm:firm.rows[0]||null,facts:facts.rows[0]||null,scores:scores.rows[0]||null,research:research.rows[0]||null,sources:sources.rows,contacts:contacts.rows,outreach:outreach.rows[0]||null,activities:activities.rows};
}
