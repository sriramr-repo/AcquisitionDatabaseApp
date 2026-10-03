import { custodianStatus, officeLines, officeStatus, yesNo } from "../../lib/adv-visibility";

const value = (v: any): string => v == null || v === "" ? "Unavailable" : typeof v === "boolean" ? yesNo(v) : typeof v === "object" ? JSON.stringify(v, null, 2) : String(v);
const date = (v: any) => v instanceof Date ? v.toISOString() : value(v);
const dollars = (v: any) => v == null ? "Unavailable" : Number(v).toLocaleString("en-US", {style:"currency",currency:"USD",maximumFractionDigits:0});
function Source({url, children}: {url?:string; children: React.ReactNode}) {
  return url && /^https?:\/\//i.test(url) ? <a href={url} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children} · link unavailable</span>;
}
function Fact({label, children}: {label: string; children: React.ReactNode}) {
  return <div className="score-row"><span>{label}</span><b>{children}</b></div>;
}
function Observations({rows}: {rows:any[]}) {
  return rows.length ? <>{rows.map(row => <article className="adv-evidence" key={row.observation_id}>
    <p><b>{row.review_status === "ACCEPTED" ? "Accepted evidence" : row.review_status === "REJECTED" ? "Rejected evidence" : "Evidence awaiting review"}</b> · {value(row.review_status)} · Confidence: {value(row.confidence)}</p>
    <pre className="adv-value">{value(row.value_json)}</pre>
    {row.source_excerpt ? <blockquote>{row.source_excerpt}</blockquote> : null}
    <Source url={row.source_url}>Filing source · {value(row.form_item)} · page {value(row.source_page)}</Source>
    <details><summary>Evidence provenance</summary><p>Captured: {date(row.created_at)} · Reviewed: {date(row.reviewed_at)} · Reviewer: {value(row.reviewer)}</p><p>{value(row.extraction_method)} · {value(row.extraction_version)}</p><code>{value(row.source_hash)}</code></details>
  </article>)}</> : <p className="muted">Unavailable — no captured facts for this dataset. This does not establish that the filing contains none.</p>;
}

export default function AdvDetails({data}: {data:any}) {
  const facts = data.advFacts || {};
  const office = data.facts || {};
  const filing = data.advFiling || {};
  const observations = data.advScheduleObservations || [];
  const rows = (key:string) => observations.filter((row:any) => row.field_key === key);
  const brochures = (data.sources || []).filter((row:any) => row.dataset_version === data.firm.dataset_version && row.source_type === "ADV_PART_2A");
  return <>
    <section className="panel" id="main-office"><h3>Main office address and phone</h3>
      <p className="muted">{officeStatus(office)} · SEC main-office facts · Dataset {data.firm.dataset_version}</p>
      <address className="adv-address">{officeLines(office).length ? officeLines(office).map((line,index)=><div key={index}>{line}</div>) : "Address unavailable"}</address>
      <Fact label="Telephone">{value(office.main_office_phone)}</Fact>
      <Fact label="Postal code">{value(office.main_office_postal_code)}</Fact>
      <p className="muted"><Source url={filing.iapd_summary_url}>Official firm profile</Source> · Address from the published SEC dataset; current online filings may be newer.</p>
    </section>
    <section className="panel" id="succession"><h3>Succession · Item 4</h3>
      <Fact label="Succession reported at this filing">{yesNo(facts.succession_indicator)}</Fact>
      <Fact label="Date of succession">{value(facts.succession_date)}</Fact>
      <Fact label="Filing date">{value(filing.filing_date)}</Fact>
      <p className="muted">This reports succession to an advisory business, including structural or legal changes. A No answer does not rule out a previously reported succession.</p>
      <Fact label="Analyst succession-readiness assessment">{value(data.research?.succession_readiness_assessment)}</Fact>
      <p className="muted">The assessment is separate from Item 4 and seller intent. <Source url={filing.pdf_url}>Current ADV PDF</Source></p>
    </section>
    <section className="panel" id="custodians"><h3>SMA custodians · Schedule D 5.K.(3)</h3>
      <p><b>{custodianStatus(facts.sma_custodian_reporting_required, data.advCustodians)}</b> · Dataset {data.firm.dataset_version}</p>
      <p className="muted">Accepted records passed automatic PDF, CRD, source-page, legal-name, and reported-AUM validation. Reporting applicability is the structured filing indicator; unavailable detail does not mean no custodian.</p>
      {data.advCustodians.length ? data.advCustodians.map((row:any)=><article className="adv-evidence" key={row.custodian_id}>
        <h4>{value(row.legal_name)}</h4>
        <Fact label="Primary business name">{value(row.primary_business_name)}</Fact>
        <Fact label="City / state / country">{[row.city,row.state,row.country].map(value).join(" / ")}</Fact>
        <Fact label="Related person">{yesNo(row.related_person)}</Fact>
        <Fact label="Broker-dealer SEC#">{value(row.broker_dealer_sec_number)}</Fact>
        <Fact label="Legal entity identifier">{value(row.legal_entity_identifier)}</Fact>
        <Fact label="Separately managed account AUM held">{dollars(row.sma_aum)}</Fact>
        <Fact label="Review / confidence">{value(row.review_status)} / {value(row.confidence)}</Fact>
        <p className="muted">Page {value(row.source_page)} · Captured {date(row.created_at)} · {value(row.extraction_method)} · {value(row.extraction_version)}</p>
        <details><summary>Source fingerprint</summary><code>{value(row.source_hash)}</code><p><Source url={filing.pdf_url}>Current ADV PDF (may differ from captured version)</Source></p></details>
      </article>) : <p className="muted">No custodian detail captured for this dataset.</p>}
    </section>
    <section className="panel" id="ownership"><h3>Ownership and control · Schedule A/B</h3>
      <p className="muted">Reported owners and principals are filing facts. Ownership codes and control flags do not by themselves establish beneficial ownership, founder status, or willingness to sell.</p>
      {data.iapdPrincipals.length ? data.iapdPrincipals.map((row:any)=><article className="adv-evidence" key={row.principal_id}>
        <h4>{value(row.full_legal_name)}</h4>
        <Fact label="Schedule / principal type">{value(row.schedule_type)} / {value(row.principal_type)}</Fact>
        <Fact label="Title / status">{value(row.title_status)}</Fact>
        <Fact label="Ownership code / control person">{value(row.ownership_code)} / {yesNo(row.control_person)}</Fact>
        <Fact label="Acquired / related CRD">{value(row.date_acquired)} / {value(row.related_crd)}</Fact>
        <p><Source url={row.source_url}>Source filing</Source> · {value(row.filing_date)}</p>
      </article>) : <p className="muted">No structured Schedule A/B principals available.</p>}
      <Observations rows={rows("adv.ownership_control")} />
    </section>
    <section className="panel" id="brochure"><h3>ADV Part 2A brochure</h3>
      <p className="muted">Document availability and parsed content are tracked separately. Proposed findings are not accepted research.</p>
      {brochures.map((row:any)=><article className="adv-evidence" key={row.source_id}><Source url={row.source_url}>{row.source_title || "Brochure"}</Source><p>{value(row.retrieval_status)} · Accessed {date(row.accessed_at)}</p><details><summary>Document fingerprint</summary><code>{value(row.content_hash)}</code></details></article>)}
      {!brochures.length ? <p className="muted">No brochure source recorded for this dataset.</p> : null}
      <Observations rows={rows("adv.brochure_intelligence")} />
    </section>
    <section className="panel" id="additional-adv"><h3>Additional ADV details</h3>
      {[["adv.custody_arrangements","Custody arrangements"],["adv.sma_structure","Separately managed accounts"],["adv.financial_affiliations","Financial affiliations"],["adv.other_business_activities","Other business activities"],["adv.client_transaction_conflicts","Transaction conflicts"],["adv.private_funds","Private funds"],["adv.disclosure_details","Disclosures"],["adv.additional_offices","Additional offices"]].map(([key,title])=><details key={key}><summary>{title}</summary><Observations rows={rows(key)} /></details>)}
    </section>
  </>;
}
