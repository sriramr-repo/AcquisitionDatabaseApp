export const dynamic = "force-dynamic";

import AdvDetails from "../../components/AdvDetails";
import RepresentativeEvidence from "../../components/RepresentativeEvidence";
import { officeLines } from "../../../lib/adv-visibility";
import { notFound } from "next/navigation";
import { firmData } from "../../../lib/queries";
import { ObservationReview, StartResearchAgent } from "./ResearchAgentControls";
import { VirtualSdrControls } from "./VirtualSdrControls";
import { AdvRefresh, SellerIntentControls } from "./AdvSellerControls";
import { sellerIntentDefinitions } from "../../../lib/seller-intent";
import SellerIntentStatus from "../../components/SellerIntentStatus";

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
  const address = officeLines(office);
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
      <div className="card"><div className="muted">Seller intent</div><div className="metric" style={{ fontSize: 18 }}><SellerIntentStatus status={data.sellerIntent?.status} /></div><small className="muted">Hover for the discrete definition.</small></div>
    </div>
    <VirtualSdrControls key={data.sdr.runs[0]?.latest_artifact_id || "no-sdr-artifact"} firmId={firmId} datasetVersion={String(data.firm.dataset_version)} initialData={JSON.parse(JSON.stringify(data.sdr))} sources={[...data.sources.map((source: any) => ({source_id: source.source_id,source_url: source.source_url,source_title: source.source_title})),...data.iapdPrincipals.map((principal: any) => ({source_id: `iapd-principal:${principal.principal_id}`,source_url: principal.source_url,source_title: `${principal.full_legal_name} · Form ADV`})),...data.contacts.filter((contact: any) => contact.verification_status === "VERIFIED").map((contact: any) => ({source_id: `contact:${contact.contact_id}`,source_url: contact.profile_url,source_title: contact.contact_name || "Verified contact"}))]} />
    <div className="detail-grid">
      <div>
        <div className="panel"><h3>Why this firm</h3>{Object.entries(components).map(([key, value]) => <div className="score-row" key={key}><span><b>{label(key)}</b><small className="score-meaning muted">{scoreMeaning[key]}</small></span><b>{val(value)}</b></div>)}<h4>Reason codes</h4>{reasons.length ? reasons.map((reason: string) => <div className="score-row" key={reason}><span>{label(reason)}</span><small className="score-meaning muted">{reasonMeaning[reason] || "SEC-derived screening signal."}</small></div>) : <p className="muted">No reason codes recorded.</p>}</div>
        <div className="panel"><h3>Business profile</h3><div className="score-row"><span>SEC#</span><b>{data.firm.sec_number || "Unavailable"}</b></div><div className="score-row"><span>Discretionary AUM</span><b>{money(data.facts?.discretionary_aum)}</b></div><div className="score-row"><span>Accounts</span><b>{val(data.facts?.total_account_count)}</b></div><div className="score-row"><span>Employees / advisory</span><b>{val(data.facts?.employee_count)} / {val(data.facts?.advisory_employee_count)}</b></div><div className="score-row"><span>Regulatory review</span><b>{data.facts?.regulatory_review_flag ? "Required" : "None recorded"}</b></div></div>
        <div className="panel adv-panel"><div className="panel-heading"><div><h3>Current Form ADV</h3><p className="muted">Official SEC structured facts, grouped by filing item. Missing values remain unavailable, not zero.</p></div><AdvRefresh firmId={firmId} /></div>
          {data.advFiling ? <div className="source-strip"><span>{data.advFiling.validation_status}</span><span>{data.advFiling.filing_date || "Filing date unavailable"}</span><a href={data.advFiling.iapd_summary_url} target="_blank" rel="noopener noreferrer">IAPD summary</a><a href={data.advFiling.pdf_url} target="_blank" rel="noopener noreferrer">Current ADV PDF</a></div> : <p className="muted">Structured ADV publication is pending.</p>}
          {data.advFacts ? <>
            <details open><summary>Firm and registration · Items 1.O, 2.A and 4</summary><div className="adv-fact-grid"><div><span>Balance-sheet assets $1B+</span><b>{data.advFacts.item_1o_over_1b == null ? "Unavailable" : data.advFacts.item_1o_over_1b ? "Yes" : "No"}</b></div><div><span>Asset band</span><b>{val(data.advFacts.item_1o_asset_band)}</b></div><div><span>Succession filing</span><b>{data.advFacts.succession_indicator == null ? "Unavailable" : data.advFacts.succession_indicator ? "Yes" : "No"}</b></div><div><span>Succession date</span><b>{val(data.advFacts.succession_date)}</b></div></div><ul className="compact-list">{(data.advFacts.sec_registration_basis || []).map((item:any)=><li key={item.code}>{item.code}. {item.label}</li>)}</ul></details>
            <details><summary>Employees · Items 5.A and 5.B</summary><div className="adv-fact-grid">{[["Employees","employee_count"],["Advisory employees","advisory_employee_count"],["Broker-dealer reps","broker_dealer_rep_count"],["State IARs","state_iar_count"],["Other-adviser IARs","other_adviser_iar_count"],["Insurance agents","insurance_agent_count"],["Solicitors","solicitor_count"]].map(([title,key])=><div key={key}><span>{title}</span><b>{countVal(data.advFacts[key])}</b></div>)}</div></details>
            <details><summary>Clients · Item 5.D</summary><div className="adv-category-table"><div className="adv-category-header"><b>Client type</b><b>Clients</b><b>&lt;5</b><b>AUM</b></div>{(data.advFacts.client_categories || []).map((item:any)=><div key={item.category_code}><span>{item.category_label}</span><span>{countVal(item.client_count)}</span><span>{item.fewer_than_five == null ? "—" : item.fewer_than_five ? "Yes" : "No"}</span><span>{money(item.aum)}</span></div>)}</div></details>
            <details><summary>Compensation · Item 5.E</summary><ul className="compact-list">{(data.advFacts.compensation_arrangements || []).map((item:any)=><li key={item.code}>{item.label}</li>)}</ul></details>
            <details><summary>Regulatory AUM and accounts · Item 5.F</summary><div className="adv-fact-grid"><div><span>Continuous management</span><b>{data.advFacts.provides_continuous_management == null ? "Unavailable" : data.advFacts.provides_continuous_management ? "Yes" : "No"}</b></div><div><span>Discretionary</span><b>{money(data.advFacts.discretionary_aum)} / {countVal(data.advFacts.discretionary_account_count)} accts.</b></div><div><span>Non-discretionary</span><b>{money(data.advFacts.non_discretionary_aum)} / {countVal(data.advFacts.non_discretionary_account_count)} accts.</b></div><div><span>Total</span><b>{money(data.advFacts.total_aum)} / {countVal(data.advFacts.total_account_count)} accts.</b></div><div><span>Non-U.S. client AUM</span><b>{money(data.advFacts.non_us_client_aum)}</b></div></div></details>
            <details><summary>Advisory activities · Item 5.G</summary><ul className="compact-list">{(data.advFacts.advisory_activities || []).map((item:any)=><li key={item.code}>{item.label}</li>)}</ul></details>
            <p><a href="#custodians">View complete custodian details and evidence status</a></p>
            <p><a href="#additional-adv">View custody, disclosures, affiliations and additional offices</a> · <a href="#brochure">Part 2A brochure</a></p>
          </> : null}
          {data.advJobs[0] ? <p className="muted">Latest refresh: {data.advJobs[0].status}{data.advJobs[0].error_message ? ` · ${data.advJobs[0].error_message}` : ""}</p> : null}
        </div>
      </div>
      <div>
        <AdvDetails data={data} />
        <div className="panel" id="iapd-representatives">
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
          {displayedRepresentatives.map((representative:any) => <details key={`evidence-${representative.individual_crd}`}><summary>{representative.full_name || representative.individual_crd} · Contact and source details</summary><RepresentativeEvidence representative={representative}/></details>)}
          {data.representatives.length > displayedRepresentatives.length ? <p className="muted">Showing the first {displayedRepresentatives.length.toLocaleString()} of {data.representatives.length.toLocaleString()} current representatives. The complete verified firm bundle remains available in Cloudflare R2.</p> : null}
          <p><a href="#ownership">View Schedule A/B owners and control details</a></p>
        </div>
        <div className="panel"><h3>Research</h3><p><b>Founder:</b> {val(data.research?.founder_name)}</p><p><b>Ownership:</b> {val(data.research?.ownership_summary)}</p><p><b>Strategic fit:</b> {val(data.research?.strategic_fit_assessment)}</p><p><b>Custodian:</b> {val(data.research?.primary_custodian)}</p></div>
        <div className="panel seller-intent-panel"><h3>Seller intent</h3><p><b>{data.sellerIntent?.status || "UNKNOWN"}</b></p><p className="muted">{sellerIntentDefinitions[data.sellerIntent?.status || "UNKNOWN"]}</p><p className="muted">This is evidence-backed and user-confirmed. SEC facts, founder age, succession proxies, staffing, and non-response cannot establish seller intent.</p><SellerIntentControls firmId={firmId} evidence={data.sellerEvidence} /></div>
        <div className="panel"><h3>Research agent</h3><p className="muted">Analyzes existing captured evidence only. Results remain proposed until reviewed.</p><StartResearchAgent firmId={firmId} />{data.agentJobs.length ? <><p><b>Latest job:</b> {data.agentJobs[0].status} · {data.agentJobs[0].model_name}{data.agentJobs[0].attempt_count != null ? ` · Attempt ${data.agentJobs[0].attempt_count}/${data.agentJobs[0].max_attempts}` : ""}</p>{["FAILED", "UNAVAILABLE"].includes(data.agentJobs[0].status) && data.agentJobs[0].error_message ? <p className="muted"><b>Reason:</b> {data.agentJobs[0].error_message}</p> : null}</> : <p className="muted">No extraction job queued.</p>}{data.observations.length ? data.observations.map((observation: any) => <div className="observation" key={observation.observation_id}><b>{label(observation.canonical_field)}</b>: {observation.proposed_value == null ? "Unavailable" : observation.proposed_value}<br /><small className="muted">{observation.value_type} · {observation.confidence || "Confidence unavailable"} · {observation.review_status}</small><blockquote>{observation.evidence_excerpt || "Evidence excerpt unavailable"}</blockquote>{observation.source_url ? <a href={observation.source_url} target="_blank" rel="noopener noreferrer">{observation.source_title || "View source"}</a> : null}{observation.source_chunk_id ? <small className="score-meaning muted">Evidence chunk: {observation.source_chunk_id}</small> : null}{observation.review_status === "PROPOSED" ? <ObservationReview observationId={observation.observation_id} /> : null}</div>) : <p className="muted">No proposed observations.</p>}</div>
        <div className="panel"><h3>Contacts</h3><div className="contact-office"><b>Main office</b><address>{address.length ? address.map((line: any, index: number) => <span key={index}>{line}</span>) : <span>Address unavailable</span>}</address><div><b>Phone:</b> {office.main_office_phone || "Unavailable"}</div></div>{data.contacts.length ? data.contacts.map((contact: any) => <p key={contact.contact_id}><b>{contact.contact_name || "Unknown"}</b> · {contact.title || "Unknown"}<br /><span className="muted">{contact.email || "Email unavailable"} · {contact.phone || "Phone unavailable"}</span></p>) : <p className="muted">No persisted contacts.</p>}</div>
        <div className="panel"><h3>Sources</h3>{data.sources.map((source: any) => <p key={source.source_id}><a href={source.source_url || "#"} target="_blank" rel="noopener noreferrer">{source.source_title || source.source_type}</a><br /><span className="muted">{source.retrieval_status || "Unknown"} · {source.accessed_at || "Unknown"}</span></p>)}</div>
      </div>
    </div>
  </>;
}
