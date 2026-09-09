import { sql } from "drizzle-orm";
import { db } from "./db";
import { getIapdFirmBundle } from "./iapd-bundles";
import { advIndicators } from "./adv-visibility";
import { virtualSdrData } from "./virtual-sdr";

export async function dashboardData(): Promise<any>{
  const [dataset, counts, research, outreach] = await Promise.all([
    db.execute(sql`select * from dataset_versions order by dataset_version desc limit 1`),
    db.execute(sql`select s.priority_category, count(*)::int as count from firm_scores s where s.dataset_version=(select dataset_version from dataset_versions order by published_at desc limit 1) group by s.priority_category order by s.priority_category`),
    db.execute(sql`select r.research_status, count(*)::int as count from firm_research r where r.dataset_version=(select dataset_version from dataset_versions order by published_at desc limit 1) group by r.research_status order by r.research_status`),
    db.execute(sql`select o.status, count(*)::int as count from outreach_targets o where o.dataset_version=(select dataset_version from dataset_versions order by published_at desc limit 1) group by o.status order by o.status`),
  ]); return {dataset: dataset.rows[0] || null, counts: counts.rows, research: research.rows, outreach: outreach.rows};
}
export async function targetData(params: {search?:string; priority?:string; sellerIntent?:string; state?:string; aum?:string; representatives?:string; iapdFreshness?:string; iapdConflict?:string; iapdDisclosure?:string; sortField?:string; sortOrder?:string; page?:number; pageSize?:number}): Promise<any>{
  const search = params.search ? `%${params.search}%` : null; const priority = params.priority || null;
  const sellerIntent = params.sellerIntent || null;
  const state = params.state?.trim().toUpperCase() || null; const aum = params.aum || null;
  const representatives = params.representatives || null; const iapdFreshness = params.iapdFreshness || null;
  const iapdConflict = params.iapdConflict === "1"; const iapdDisclosure = params.iapdDisclosure === "1";
  const sortFields: Record<string,string> = { score: "acquisition_score", aum: "total_aum", accounts: "total_account_count", employees: "employee_count", representatives: "representative_count" };
  const sortColumn = sql.raw(sortFields[params.sortField || "score"] || sortFields.score); const sortOrder = params.sortOrder === "asc" ? sql.raw("asc") : sql.raw("desc");
  const page = Math.max(1, params.page || 1); const size = Math.min(100, Math.max(10, params.pageSize || 25)); const offset=(page-1)*size;
  const targetBase = sql`with active as (select dataset_version from dataset_versions order by published_at desc,dataset_version desc limit 1),
    latest_summary as (select distinct on (firm_id) * from iapd_firm_summaries order by firm_id,snapshot_date desc,published_at desc),
    latest_reconciliation as (select distinct on (individual_crd) * from iapd_individual_reconciliations order by individual_crd,created_at desc),
    reconciliation_links as (select distinct rc.individual_crd,rc.freshness,rc.conflicts,links.firm_id
      from latest_reconciliation rc cross join lateral (
        select rc.effective_fields->>'current_employer_crd' firm_id
        union select employer->>'crd' from jsonb_array_elements(coalesce(rc.effective_fields->'current_employers','[]'::jsonb)) employer
      ) links where links.firm_id is not null),
    reconciliation_by_firm as (select firm_id,
      count(*)::int live_representative_count,count(*) filter (where freshness='conflict' or conflicts<>'{}'::jsonb)::int conflict_count,
      count(*) filter (where freshness in ('partial','missing'))::int partial_count
      from reconciliation_links group by 1),
    base as (select f.firm_id,f.dataset_version,f.name,coalesce(x.main_office_state,f.organization_state) organization_state,
      s.priority_category,s.acquisition_score,s.review_required,x.total_aum,x.discretionary_aum,x.individual_hnw_share,
      x.total_account_count,x.average_account_size,x.employee_count,x.advisory_employee_count,r.research_status,
      o.status outreach_status,coalesce(si.status,'UNKNOWN') seller_intent_status,
      sm.representative_count,sm.active_representative_count,sm.representative_with_disclosure_count,
      coalesce(rb.conflict_count,0)::int iapd_conflict_count,
      case when coalesce(rb.conflict_count,0)>0 then 'conflict'
           when sm.snapshot_id is null then 'missing'
           when sm.snapshot_date::date < current_date-45 then 'partial'
           when coalesce(rb.partial_count,0)>0 then 'partial'
           else 'monthly_confirmed' end iapd_freshness,
      sm.snapshot_date iapd_snapshot_date
      from firms f join active a using(dataset_version) join firm_scores s using(firm_id,dataset_version)
      left join firm_facts x using(firm_id,dataset_version) left join firm_research r using(firm_id,dataset_version)
      left join outreach_targets o using(firm_id,dataset_version) left join seller_intent_current si using(firm_id,dataset_version)
      left join latest_summary sm on sm.firm_id=f.firm_id left join reconciliation_by_firm rb on rb.firm_id=f.firm_id)
    select * from base where (${search}::text is null or name ilike ${search} or firm_id ilike ${search})
      and (${priority}::text is null or priority_category=${priority})
      and (${sellerIntent}::text is null or seller_intent_status=${sellerIntent})
      and (${state}::text is null or upper(organization_state)=${state})
      and (${aum}::text is null or (${aum}='under200' and total_aum<200000000) or (${aum}='unknown' and total_aum is null))
      and (${representatives}::text is null or (${representatives}='none' and representative_count=0) or (${representatives}='any' and representative_count>0) or (${representatives}='1to3' and representative_count between 1 and 3) or (${representatives}='4plus' and representative_count>=4))
      and (${iapdFreshness}::text is null or iapd_freshness=${iapdFreshness})
      and (not ${iapdConflict} or iapd_conflict_count>0)
      and (not ${iapdDisclosure} or representative_with_disclosure_count>0)`;
  const rows = await db.execute(sql`${targetBase} order by ${sortColumn} ${sortOrder} nulls last, firm_id limit ${size} offset ${offset}`);
  const total = await db.execute(sql`select count(*)::int count from (${targetBase}) filtered`);
  const universe = await db.execute(sql`select count(*)::int count from firms where dataset_version=(select dataset_version from dataset_versions order by published_at desc,dataset_version desc limit 1)`);
  const coverage = rows.rows.length ? await db.execute(sql`select f.firm_id,
      x.main_office_street_address_1,x.main_office_street_address_2,x.main_office_city,x.main_office_state,x.main_office_country,x.main_office_phone,
      to_jsonb(x)->>'main_office_postal_code' as main_office_postal_code,
      a.succession_indicator,a.sma_custodian_reporting_required,
      exists(select 1 from iapd_firm_principals p where p.firm_id=f.firm_id) as has_principals,
      coalesce((select jsonb_agg(jsonb_build_object('review_status',c.review_status)) from adv_custodians c where c.firm_id=f.firm_id and c.dataset_version=f.dataset_version),'[]'::jsonb) as custodians,
      coalesce((select jsonb_agg(jsonb_build_object('field_key',o.field_key,'review_status',o.review_status)) from adv_schedule_observations o where o.firm_id=f.firm_id and o.dataset_version=f.dataset_version and o.field_key in ('adv.ownership_control','adv.brochure_intelligence')),'[]'::jsonb) as schedule_observations
      from firms f left join firm_facts x using(firm_id,dataset_version) left join adv_firm_facts a using(firm_id,dataset_version)
      where f.dataset_version=${rows.rows[0].dataset_version} and f.firm_id in (${sql.join(rows.rows.map(row => sql`${row.firm_id}`), sql`,`)})`) : {rows:[]};
  const indicators = new Map(coverage.rows.map(row => [row.firm_id, advIndicators(row)]));
  return {rows: rows.rows.map(row => ({...row,...indicators.get(row.firm_id)})), total: Number(total.rows[0]?.count || 0), universeTotal:Number(universe.rows[0]?.count || 0), page, pageSize:size};
}
export async function firmData(firmId:string): Promise<any>{
  const activeDataset = sql`(select dataset_version from dataset_versions order by published_at desc, dataset_version desc limit 1)`;
  const [firm,facts,scores,research,sources,contacts,outreach,activities,representatives,iapdSummary,iapdCoverage,iapdPrincipals,agentJobs,observations,advFiling,advFacts,advCustodians,advScheduleObservations,advJobs,sellerIntent,sellerEvidence,sellerHistory] = await Promise.all([
    db.execute(sql`select * from firms where firm_id=${firmId} and dataset_version=${activeDataset} limit 1`),
    db.execute(sql`select x.* from firm_facts x where firm_id=${firmId} and dataset_version=${activeDataset} limit 1`),
    db.execute(sql`select s.* from firm_scores s where firm_id=${firmId} and dataset_version=${activeDataset} limit 1`),
    db.execute(sql`select r.* from firm_research r where firm_id=${firmId} and dataset_version=${activeDataset} limit 1`),
    db.execute(sql`select * from research_sources where firm_id=${firmId} order by accessed_at desc nulls last`),
    db.execute(sql`select * from contacts where firm_id=${firmId} order by contact_name`),
    db.execute(sql`select * from outreach_targets where firm_id=${firmId} and dataset_version=${activeDataset} limit 1`),
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
    db.execute(sql`select * from adv_current_filings where firm_id=${firmId} and dataset_version=${activeDataset} limit 1`),
    db.execute(sql`select * from adv_firm_facts where firm_id=${firmId} and dataset_version=${activeDataset} limit 1`),
    db.execute(sql`select * from adv_custodians where firm_id=${firmId} and dataset_version=${activeDataset} order by legal_name`),
    db.execute(sql`select * from adv_schedule_observations where firm_id=${firmId} and dataset_version=${activeDataset} order by form_item,field_key,created_at desc`),
    db.execute(sql`select * from adv_refresh_jobs where firm_id=${firmId} and dataset_version=${activeDataset} order by created_at desc limit 5`),
    db.execute(sql`select * from seller_intent_current where firm_id=${firmId} and dataset_version=${activeDataset} limit 1`),
    db.execute(sql`select * from seller_intent_evidence where firm_id=${firmId} order by evidence_date desc limit 50`),
    db.execute(sql`select * from seller_intent_history where firm_id=${firmId} order by changed_at desc limit 50`),
  ]);
  const firmRecord:any = firm.rows[0] || null;
  const detail:any = firmRecord
    ? await getIapdFirmBundle(String(firmRecord.dataset_version), firmId)
    : {status:"FAILED",message:"Firm not found"};
  const sdr = firmRecord ? await virtualSdrData(firmId) : {runs:[],artifacts:[],reviews:[],qualityChecks:[]};
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
  // Live evidence also decorates R2-backed representatives. It never replaces the firm.
  const crds = representativeRows.map(row => String(row.individual_crd));
  const liveEvidence = await db.execute(sql`
    with latest as (select distinct on (individual_crd) * from iapd_individual_reconciliations
      order by individual_crd,created_at desc)
    select rc.*,lc.retrieved_at as source_retrieved_at,lc.source_url
    from latest rc left join iapd_live_captures lc on lc.capture_id=rc.capture_id
    where rc.individual_crd in (select jsonb_array_elements_text(${JSON.stringify(crds)}::jsonb))
       or (rc.effective_fields->>'current_employer_crd'=${firmId} and rc.capture_id is not null)
  `);
  const evidence = new Map((liveEvidence.rows as any[]).map(row => [row.individual_crd,row]));
  representativeRows = representativeRows.map(row => {
    const live = evidence.get(String(row.individual_crd));
    return live ? {...row,effective_fields:live.effective_fields,freshness:live.freshness,
      conflicts:live.conflicts,last_retrieved_at:live.source_retrieved_at,source_url:live.source_url} : row;
  });
  for (const live of liveEvidence.rows as any[]) {
    if (!crds.includes(live.individual_crd) && live.effective_fields?.current_employer_crd === firmId) {
      representativeRows.push({individual_crd:live.individual_crd,full_name:live.effective_fields.full_name,
        effective_fields:live.effective_fields,freshness:live.freshness,conflicts:live.conflicts,
        last_retrieved_at:live.source_retrieved_at,source_url:live.source_url});
    }
  }
  return {firm:firmRecord,facts:facts.rows[0]||null,scores:scores.rows[0]||null,research:research.rows[0]||null,sources:sources.rows,contacts:contacts.rows,outreach:outreach.rows[0]||null,activities:activities.rows,representatives:representativeRows,iapdDetail:detailStatus,iapdSummary:iapdSummary.rows[0]||null,iapdCoverage:iapdCoverage.rows[0]||null,iapdPrincipals:iapdPrincipals.rows,agentJobs:agentJobs.rows,observations:observations.rows,advFiling:advFiling.rows[0]||null,advFacts:advFacts.rows[0]||null,advCustodians:advCustodians.rows,advScheduleObservations:advScheduleObservations.rows,advJobs:advJobs.rows,sellerIntent:sellerIntent.rows[0]||null,sellerEvidence:sellerEvidence.rows,sellerHistory:sellerHistory.rows,sdr};
}

export async function advCoverageData(): Promise<any> {
  const [facts,jobs,custodians] = await Promise.all([
    db.execute(sql`select count(*)::int as total, count(*) filter (where sma_custodian_reporting_required is true)::int as applicable, count(*) filter (where sma_custodian_reporting_required is false)::int as not_required, count(*) filter (where sma_custodian_reporting_required is null)::int as unavailable from adv_firm_facts where dataset_version=(select dataset_version from dataset_versions order by published_at desc limit 1)`),
    db.execute(sql`with latest as (select distinct on (firm_id) firm_id,status from adv_refresh_jobs where dataset_version=(select dataset_version from dataset_versions order by published_at desc limit 1) order by firm_id,created_at desc) select status,count(*)::int as count from latest group by status order by status`),
    db.execute(sql`select count(*)::int as rows,count(distinct firm_id)::int as firms from adv_custodians where dataset_version=(select dataset_version from dataset_versions order by published_at desc limit 1)`),
  ]);
  return {facts:facts.rows[0]||{}, jobs:jobs.rows, custodians:custodians.rows[0]||{}};
}

export async function factDictionaryData(): Promise<any[]> {
  const result = await db.execute(sql`select * from fact_definitions where active=true order by dashboard_section,display_order,field_key`);
  return result.rows as any[];
}
