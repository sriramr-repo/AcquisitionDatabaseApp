export const dynamic = "force-dynamic";

import { notFound } from "next/navigation";
import { firmData } from "../../../lib/queries";
import { ObservationReview, StartResearchAgent } from "./ResearchAgentControls";

const val = (value: any) => value == null ? "Unavailable" : typeof value === "number" ? value.toFixed(1) : String(value);
const countVal = (value: any) => value == null ? "Unavailable" : Number(value).toLocaleString();
const money = (value: any) => value == null ? "Unavailable" : `$${(Number(value) / 1e6).toFixed(1)}M`;
const label = (key: string) => key.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());

const scoreMeaning: Record<string, string> = {
  aum_fit_score: "AUM is in the $20M–$100M target range, with $25M–$60M preferred.",
  client_fit_score: "Measures individual/HNW client concentration.",
  discretionary_fit_score: "Measures discretionary AUM share and size.",
  advisory_model_fit_score: "Rewards individual/small-business and financial-planning models; subtracts complexity penalties.",
  regulatory_quality_score: "Reflects the current Item 11 regulatory disclosure review.",
  practice_complexity_score: "Rewards a small team and simple reported control structure.",
  account_practice_fit_score: "Measures account scale, average account size, and discretionary account share.",
};

const reasonMeaning: Record<string, string> = {
  PREFERRED_AUM_BAND: "AUM is between $25M and $60M.",
  HIGH_DISCRETIONARY_SHARE: "At least 90% of AUM is discretionary.",
  PREDOMINANTLY_DISCRETIONARY: "At least 75% of AUM is discretionary.",
  MEANINGFUL_DISCRETIONARY_AUM: "Discretionary AUM is at least $25M.",
  HNW_INDIVIDUAL_FOCUSED: "At least 75% of AUM is individual/HNW.",
  HIGH_HNW_AUM_SHARE: "At least 50% of AUM is HNW.",
  MANAGEABLE_ACCOUNT_BASE: "500 or fewer accounts.",
  HIGH_AVERAGE_ACCOUNT_SIZE: "Average account size is at least $500,000.",
  HIGH_DISCRETIONARY_ACCOUNT_SHARE: "At least 75% of accounts are discretionary.",
  SMALL_EMPLOYEE_BASE: "Three or fewer employees.",
  SMALL_ADVISORY_TEAM: "Three or fewer advisory employees.",
  SIMPLE_CONTROL_STRUCTURE: "No reported related-person or common-control complexity.",
  INDIVIDUAL_SMALL_BUSINESS_MODEL: "Advises individuals or small businesses.",
  FINANCIAL_PLANNING_MODEL: "Provides financial planning.",
  CLEAN_ITEM11_HISTORY: "No reported Item 11 regulatory disclosure issue.",
};

const iapdMeaning: Record<string, string> = {
  CURRENT_IAPD_REPRESENTATIVE: "Current representatives are linked to this firm in the official monthly IAPD individual feed.",
  SCHEDULE_A_PRINCIPAL: "No current representative link was found; Form ADV Schedule A identifies an individual owner or executive.",
  SCHEDULE_B_OWNER: "No current representative link was found; Form ADV Schedule B identifies an individual indirect owner.",
  ENTITY_OWNER_ONLY: "Form ADV reports an entity owner, but no current individual representative or individual principal is available.",
  CCO_OR_SIGNATORY_ONLY: "Only the Form ADV compliance officer or authorized signatory is available.",
  NO_PUBLIC_INDIVIDUAL_PROFILE: "The official sources were processed, but no searchable current individual profile is available.",
  RECONCILIATION_REQUIRED: "Form ADV reports state-registered IARs, but the monthly individual feed has no matching current-employment link.",
  SOURCE_NOT_PROCESSED: "The required official source has not been processed for this firm.",
  SOURCE_RETRIEVAL_FAILED: "The official source could not be retrieved; this is a source failure, not a confirmed absence.",
};

export default async function Firm({ params }: { params: Promise<{ firmId: string }> }) {
  const { firmId } = await params;
  const data = await firmData(firmId);
  if (!data.firm) notFound();

  const scores = data.scores || {};
  const components = scores.component_scores || {};
  const reasons = Array.isArray(scores.reason_codes) ? scores.reason_codes : [];
  const office = data.facts || {};
  const address = [office.main_office_street_address_1, office.main_office_street_address_2, [office.main_office_city, office.main_office_state].filter(Boolean).join(", "), office.main_office_country].filter(Boolean);
  const coverageStatus = data.iapdCoverage?.coverage_status || "SOURCE_NOT_PROCESSED";
  const coverageMeaning = iapdMeaning[coverageStatus] || "IAPD personnel coverage is unavailable.";
  const displayedRepresentatives = data.representatives.slice(0, 200);

  return <>
    <div className="top"><div><h2>{data.firm.name || firmId}</h2><p className="muted">CRD {firmId} · {data.firm.organization_state || "Unknown"} · <a href={data.firm.website_address || "#"} target="_blank" rel="noopener noreferrer">{data.firm.website_address || "Website unavailable"}</a></p></div><span className="badge good">{scores.priority_category || "Unavailable"}</span></div>
    <div className="grid">
      <div className="card"><div className="muted">Acquisition score</div><div className="metric">{val(scores.acquisition_score)}</div></div>
      <div className="card"><div className="muted">AUM</div><div className="metric">{money(data.facts?.total_aum)}</div></div>
      <div className="card"><div className="muted">Research</div><div className="metric" style={{ fontSize: 18 }}>{data.research?.research_status || "NOT_STARTED"}</div></div>
      <div className="card"><div className="muted">Outreach</div><div className="metric" style={{ fontSize: 18 }}>{data.outreach?.status || "NOT_RESEARCHED"}</div></div>
    </div>
    <div className="detail-grid">
      <div>
        <div className="panel"><h3>Why this firm</h3>{Object.entries(components).map(([key, value]) => <div className="score-row" key={key}><span><b>{label(key)}</b><small className="score-meaning muted">{scoreMeaning[key]}</small></span><b>{val(value)}</b></div>)}<h4>Reason codes</h4>{reasons.length ? reasons.map((reason: string) => <div className="score-row" key={reason}><span>{label(reason)}</span><small className="score-meaning muted">{reasonMeaning[reason] || "SEC-derived screening signal."}</small></div>) : <p className="muted">No reason codes recorded.</p>}</div>
        <div className="panel"><h3>Business profile</h3><div className="score-row"><span>SEC#</span><b>{data.firm.sec_number || "Unavailable"}</b></div><div className="score-row"><span>Discretionary AUM</span><b>{money(data.facts?.discretionary_aum)}</b></div><div className="score-row"><span>Accounts</span><b>{val(data.facts?.total_account_count)}</b></div><div className="score-row"><span>Employees / advisory</span><b>{val(data.facts?.employee_count)} / {val(data.facts?.advisory_employee_count)}</b></div><div className="score-row"><span>Regulatory review</span><b>{data.facts?.regulatory_review_flag ? "Required" : "None recorded"}</b></div></div>
      </div>
      <div>
        <div className="panel">
          <h3>IAPD personnel coverage</h3>
          <div className="score-row"><span><b>{label(coverageStatus)}</b><small className="score-meaning muted">{coverageMeaning}</small></span><span className="badge">{data.iapdCoverage ? "Classified" : "Pending"}</span></div>
          <div className="score-row"><span>Detail source</span><b>{data.iapdDetail?.source === "CLOUDFLARE_R2" ? "Cloudflare R2" : data.iapdDetail?.source === "NEON" ? "Hosted fallback" : "Unavailable"}</b></div>
          {data.iapdDetail?.message ? <p className="muted">{data.iapdDetail.message}</p> : null}
          <div className="score-row"><span>Current representatives</span><b>{countVal(data.iapdCoverage?.representative_count)}</b></div>
          <div className="score-row"><span>Individual principals</span><b>{countVal(data.iapdCoverage?.individual_principal_count)}</b></div>
          <div className="score-row"><span>Entity principals</span><b>{countVal(data.iapdCoverage?.entity_principal_count)}</b></div>
          <div className="score-row"><span>State IARs reported on ADV</span><b>{countVal(data.iapdCoverage?.reported_state_iar_count)}</b></div>
          <h4>Current IAPD representatives</h4>
          {data.representatives.length ? displayedRepresentatives.map((representative: any) => {
            const effective = representative.effective_fields || {};
            const conflicts = representative.conflicts || {};
            const registrations = Array.isArray(representative.current_registrations) ? representative.current_registrations : [];
            return <div className="score-row" key={representative.individual_crd}><span><b>{representative.full_name || effective.full_name || "Unnamed representative"}</b><small className="score-meaning muted">CRD {representative.individual_crd} · {registrations.map((registration: any) => [registration.authority, registration.status, registration.status_date].filter(Boolean).join(" · ")).filter(Boolean).join("; ") || effective.registration_status || "Registration unavailable"}{representative.has_disclosures ? " · Disclosure reported" : ""}{representative.has_other_business ? " · Other business reported" : ""}<br />Source: {representative.freshness || "monthly_confirmed"} · Retrieved: {representative.last_retrieved_at || "monthly snapshot"}{effective.phone ? ` · Phone: ${effective.phone}` : ""}{effective.website ? ` · Website: ${effective.website}` : ""}{Object.keys(conflicts).length ? " · Conflict requires review" : ""}</small></span><b>{representative.active_ag_registration === true ? "Active" : representative.active_ag_registration === false ? "Not active" : "Status unavailable"}</b></div>;
          }) : <p className="muted">{coverageMeaning}</p>}
          {data.representatives.length > displayedRepresentatives.length ? <p className="muted">Showing the first {displayedRepresentatives.length.toLocaleString()} of {data.representatives.length.toLocaleString()} current representatives. The complete verified firm bundle remains available in Cloudflare R2.</p> : null}
          {data.iapdPrincipals.length ? <><h4>Form ADV principals and owners</h4>{data.iapdPrincipals.map((principal: any) => <div className="score-row" key={principal.principal_id}><span><b>{principal.full_legal_name}</b><small className="score-meaning muted">Schedule {principal.schedule_type} · {label(principal.principal_type)}{principal.title_status ? ` · ${principal.title_status}` : ""}{principal.ownership_code ? ` · Ownership ${principal.ownership_code}` : ""}{principal.control_person === true ? " · Control person" : ""}{principal.related_crd ? ` · CRD ${principal.related_crd}` : ""}</small></span><b>{principal.filing_date || "Date unavailable"}</b></div>)}</> : null}
        </div>
        <div className="panel"><h3>Research</h3><p><b>Founder:</b> {val(data.research?.founder_name)}</p><p><b>Ownership:</b> {val(data.research?.ownership_summary)}</p><p><b>Strategic fit:</b> {val(data.research?.strategic_fit_assessment)}</p><p><b>Custodian:</b> {val(data.research?.primary_custodian)}</p></div>
        <div className="panel"><h3>Research agent</h3><p className="muted">Analyzes existing captured evidence only. Results remain proposed until reviewed.</p><StartResearchAgent firmId={firmId} />{data.agentJobs.length ? <><p><b>Latest job:</b> {data.agentJobs[0].status} · {data.agentJobs[0].model_name}{data.agentJobs[0].attempt_count != null ? ` · Attempt ${data.agentJobs[0].attempt_count}/${data.agentJobs[0].max_attempts}` : ""}</p>{["FAILED", "UNAVAILABLE"].includes(data.agentJobs[0].status) && data.agentJobs[0].error_message ? <p className="muted"><b>Reason:</b> {data.agentJobs[0].error_message}</p> : null}</> : <p className="muted">No extraction job queued.</p>}{data.observations.length ? data.observations.map((observation: any) => <div className="observation" key={observation.observation_id}><b>{label(observation.canonical_field)}</b>: {observation.proposed_value == null ? "Unavailable" : observation.proposed_value}<br /><small className="muted">{observation.value_type} · {observation.confidence || "Confidence unavailable"} · {observation.review_status}</small><blockquote>{observation.evidence_excerpt || "Evidence excerpt unavailable"}</blockquote>{observation.source_url ? <a href={observation.source_url} target="_blank" rel="noopener noreferrer">{observation.source_title || "View source"}</a> : null}{observation.source_chunk_id ? <small className="score-meaning muted">Evidence chunk: {observation.source_chunk_id}</small> : null}{observation.review_status === "PROPOSED" ? <ObservationReview observationId={observation.observation_id} /> : null}</div>) : <p className="muted">No proposed observations.</p>}</div>
        <div className="panel"><h3>Contacts</h3><div className="contact-office"><b>Main office</b><address>{address.length ? address.map((line: any, index: number) => <span key={index}>{line}</span>) : <span>Address unavailable</span>}</address><div><b>Phone:</b> {office.main_office_phone || "Unavailable"}</div></div>{data.contacts.length ? data.contacts.map((contact: any) => <p key={contact.contact_id}><b>{contact.contact_name || "Unknown"}</b> · {contact.title || "Unknown"}<br /><span className="muted">{contact.email || "Email unavailable"} · {contact.phone || "Phone unavailable"}</span></p>) : <p className="muted">No persisted contacts.</p>}</div>
        <div className="panel"><h3>Sources</h3>{data.sources.map((source: any) => <p key={source.source_id}><a href={source.source_url || "#"} target="_blank" rel="noopener noreferrer">{source.source_title || source.source_type}</a><br /><span className="muted">{source.retrieval_status || "Unknown"} · {source.accessed_at || "Unknown"}</span></p>)}</div>
      </div>
    </div>
  </>;
}
