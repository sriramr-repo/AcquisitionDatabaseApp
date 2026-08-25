import { sql } from "drizzle-orm";
import { db } from "./db";
import { getIapdFirmBundle } from "./iapd-bundles";

export async function dashboardData(): Promise<any>{
  const [dataset, counts, research, outreach] = await Promise.all([
    db.execute(sql`select * from dataset_versions order by dataset_version desc limit 1`),
    db.execute(sql`select s.priority_category, count(*)::int as count from firm_scores s where s.dataset_version=(select dataset_version from dataset_versions order by published_at desc limit 1) group by s.priority_category order by s.priority_category`),
    db.execute(sql`select r.research_status, count(*)::int as count from firm_research r where r.dataset_version=(select dataset_version from dataset_versions order by published_at desc limit 1) group by r.research_status order by r.research_status`),
    db.execute(sql`select o.status, count(*)::int as count from outreach_targets o where o.dataset_version=(select dataset_version from dataset_versions order by published_at desc limit 1) group by o.status order by o.status`),
  ]); return {dataset: dataset.rows[0] || null, counts: counts.rows, research: research.rows, outreach: outreach.rows};
}
export async function targetData(params: {search?:string; priority?:string; sortField?:string; sortOrder?:string; page?:number; pageSize?:number}): Promise<any>{
  const search = params.search ? `%${params.search}%` : null; const priority = params.priority || null;
  const sortFields: Record<string,string> = { score: "s.acquisition_score", aum: "x.total_aum", accounts: "x.total_account_count", employees: "x.employee_count" };
  const sortColumn = sql.raw(sortFields[params.sortField || "score"] || sortFields.score); const sortOrder = params.sortOrder === "asc" ? sql.raw("asc") : sql.raw("desc");
  const page = Math.max(1, params.page || 1); const size = Math.min(100, Math.max(10, params.pageSize || 25)); const offset=(page-1)*size;
  const rows = await db.execute(sql`select f.firm_id, f.dataset_version, f.name, f.organization_state, s.priority_category, s.acquisition_score, s.review_required, x.total_aum, x.discretionary_aum, x.individual_hnw_share, x.total_account_count, x.average_account_size, x.employee_count, x.advisory_employee_count, r.research_status, o.status as outreach_status
    from firms f join firm_scores s using (firm_id,dataset_version) left join firm_facts x using (firm_id,dataset_version) left join firm_research r using (firm_id,dataset_version) left join outreach_targets o using (firm_id,dataset_version)
    where f.dataset_version=(select dataset_version from dataset_versions order by published_at desc limit 1) and (${search}::text is null or f.name ilike ${search} or f.firm_id::text ilike ${search}) and (${priority}::text is null or s.priority_category=${priority}) order by ${sortColumn} ${sortOrder} nulls last, f.firm_id limit ${size} offset ${offset}`);
  const total = await db.execute(sql`select count(*)::int as count from firms f join firm_scores s using (firm_id,dataset_version) where f.dataset_version=(select dataset_version from dataset_versions order by published_at desc limit 1) and (${search}::text is null or f.name ilike ${search} or f.firm_id::text ilike ${search}) and (${priority}::text is null or s.priority_category=${priority})`);
  return {rows: rows.rows, total: Number(total.rows[0]?.count || 0), page, pageSize:size};
}
export async function firmData(firmId:string): Promise<any>{
  const [firm,facts,scores,research,sources,contacts,outreach,activities,representatives,iapdSummary,iapdCoverage,iapdPrincipals,agentJobs,observations] = await Promise.all([
    db.execute(sql`select * from firms where firm_id=${firmId} order by dataset_version desc limit 1`),
    db.execute(sql`select x.* from firm_facts x where firm_id=${firmId} order by dataset_version desc limit 1`),
    db.execute(sql`select s.* from firm_scores s where firm_id=${firmId} order by dataset_version desc limit 1`),
    db.execute(sql`select r.* from firm_research r where firm_id=${firmId} order by dataset_version desc limit 1`),
    db.execute(sql`select * from research_sources where firm_id=${firmId} order by accessed_at desc nulls last`),
    db.execute(sql`select * from contacts where firm_id=${firmId} order by contact_name`),
    db.execute(sql`select * from outreach_targets where firm_id=${firmId} order by dataset_version desc limit 1`),
    db.execute(sql`select * from outreach_activities where firm_id=${firmId} order by occurred_at desc`),
    db.execute(sql`with latest_snapshot as (
      select snapshot_id from iapd_individual_snapshots where status='SUCCESS' order by snapshot_date desc limit 1
    ) select i.individual_crd,i.full_name,i.active_ag_registration,i.composite_link,e.employer_name,e.employer_firm_crd,
      e.address_line_1,e.address_line_2,e.city,e.state,e.postal_code,e.country,
      coalesce(jsonb_agg(distinct jsonb_build_object('authority',r.authority,'category',r.category,'status',r.status,'status_date',r.status_date)) filter (where r.registration_id is not null),'[]'::jsonb) as current_registrations,
      coalesce(bool_or(coalesce(d.reg_action,false) or coalesce(d.criminal,false) or coalesce(d.bankrupt,false) or coalesce(d.civil_judgment,false) or coalesce(d.bond,false) or coalesce(d.judgment,false) or coalesce(d.investigation,false) or coalesce(d.customer_complaint,false) or coalesce(d.termination,false)),false) as has_disclosures,
      coalesce(bool_or(ob.other_business_id is not null),false) as has_other_business,
      coalesce(rc.freshness,'monthly_confirmed') as freshness, rc.effective_fields, rc.conflicts, rc.created_at as last_retrieved_at
      from iapd_individual_current_employments e join latest_snapshot s on s.snapshot_id=e.snapshot_id
      join iapd_individuals i on i.individual_crd=e.individual_crd
      left join iapd_individual_current_registrations r on r.snapshot_id=e.snapshot_id and r.employment_id=e.employment_id
      left join iapd_individual_disclosure_flags d on d.snapshot_id=e.snapshot_id and d.individual_crd=e.individual_crd
      left join iapd_individual_other_businesses ob on ob.snapshot_id=e.snapshot_id and ob.individual_crd=e.individual_crd
      left join lateral (select freshness,effective_fields,conflicts,created_at from iapd_individual_reconciliations where individual_crd=e.individual_crd order by created_at desc limit 1) rc on true
      where e.employer_firm_crd=${firmId}
      group by i.individual_crd,i.full_name,i.active_ag_registration,i.composite_link,e.employer_name,e.employer_firm_crd,e.address_line_1,e.address_line_2,e.city,e.state,e.postal_code,e.country,rc.freshness,rc.effective_fields,rc.conflicts,rc.created_at
      order by i.full_name nulls last`),
    db.execute(sql`select * from iapd_firm_summaries where firm_id=${firmId} order by snapshot_date desc limit 1`),
    db.execute(sql`select * from iapd_firm_coverage where firm_id=${firmId} order by dataset_version desc limit 1`),
    db.execute(sql`with latest as (select max(filing_date) filing_date from iapd_firm_principals where firm_id=${firmId})
      select * from iapd_firm_principals where firm_id=${firmId}
        and filing_date is not distinct from (select filing_date from latest)
      order by schedule_type,principal_type,full_legal_name`),
    db.execute(sql`select * from research_agent_jobs where firm_id=${firmId} order by created_at desc limit 10`),
    db.execute(sql`select o.*,s.source_url,s.source_title,coalesce(c.content_hash,lc.content_hash) as capture_content_hash,
      (o.agent_job_id is null or (j.prompt_version='scm-research-prompt-v7' and j.extraction_version='scm-research-extraction-v7')) as contract_current
      from research_observations o join research_sources s on s.source_id=o.source_id
      left join research_agent_jobs j on j.job_id=o.agent_job_id
      left join research_evidence_captures c on c.capture_id=o.source_capture_id
      left join iapd_live_captures lc on lc.capture_id=o.source_capture_id
      where o.firm_id=${firmId}
        and (o.agent_job_id is null or (j.prompt_version='scm-research-prompt-v7' and j.extraction_version='scm-research-extraction-v7'))
      order by o.created_at desc limit 100`),
  ]);
  const firmRecord:any = firm.rows[0] || null;
  const detail:any = firmRecord
    ? await getIapdFirmBundle(String(firmRecord.dataset_version), firmId)
    : {status:"FAILED",message:"Firm not found"};
  let representativeRows:any[] = representatives.rows as any[];
  let detailStatus:any = detail;
  if (detail.status === "AVAILABLE") {
    representativeRows = (detail.bundle?.representatives || []).map((representative:any) => ({
      ...representative,
      ...(representative.current_employment || {}),
    }));
    detailStatus = {
      status: detail.status,
      source: "CLOUDFLARE_R2",
      snapshot_date: detail.bundle?.snapshot_date,
      representative_count: detail.bundle?.representative_count,
    };
  } else if (detail.status === "NO_CURRENT_REPRESENTATIVE") {
    representativeRows = [];
  } else if (representativeRows.length) {
    detailStatus = {
      status: "LEGACY_FALLBACK",
      source: "NEON",
      message: detail.message || "Cloudflare R2 detail is unavailable; using the verified hosted fallback.",
    };
  }
  return {firm:firmRecord,facts:facts.rows[0]||null,scores:scores.rows[0]||null,research:research.rows[0]||null,sources:sources.rows,contacts:contacts.rows,outreach:outreach.rows[0]||null,activities:activities.rows,representatives:representativeRows,iapdDetail:detailStatus,iapdSummary:iapdSummary.rows[0]||null,iapdCoverage:iapdCoverage.rows[0]||null,iapdPrincipals:iapdPrincipals.rows,agentJobs:agentJobs.rows,observations:observations.rows};
}
