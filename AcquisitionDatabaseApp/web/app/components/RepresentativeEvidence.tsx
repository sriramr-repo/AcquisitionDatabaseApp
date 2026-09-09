export default function RepresentativeEvidence({representative:r}:{representative:any}) {
  const e = r.effective_fields || {};
  const address = [r.address_line_1,r.address_line_2,r.city,r.state,r.postal_code,r.country].filter(Boolean).join(', ');
  const values = [
    ['Employer',r.employer_name || e.current_employer_name],
    ['Business address',address || e.business_address],
    ['Registration date',e.registration_date],
    ['Phone',e.phone],['Website',e.website],
    ['Branches',Array.isArray(e.branch_locations) ? e.branch_locations.map((b:any)=>typeof b==='string'?b:JSON.stringify(b)).join('; ') : null],
    ['Disclosures',e.disclosure_summary],
  ];
  return <div className="muted" style={{fontSize:'0.8rem',margin:'0.4rem 0 1rem'}}>
    {values.map(([name,value])=><div key={name}><span>{name}: </span>{value == null || value === '' ? 'Unavailable' : value}</div>)}
    <div>Freshness: {r.freshness || 'partial'}</div>
    <div>Live evidence retrieved: {r.last_retrieved_at ? String(r.last_retrieved_at) : 'Unavailable'}</div>
    {e.provenance ? <details><summary>Field sources</summary>{Object.entries(e.provenance).map(([field,source]:[string,any])=><div key={field}>{field.replaceAll('_',' ')}: {source.source_type === 'monthly_feed' ? 'Monthly compilation' : 'Live IAPD page'} · {source.observed_at || 'Date unavailable'}</div>)}</details> : null}
    {e.stale ? <div>Refresh needed: evidence is outside the freshness window.</div> : null}
    {r.source_url ? <a href={r.source_url} target="_blank" rel="noopener noreferrer">View IAPD evidence</a> : null}
    {Object.keys(r.conflicts || {}).length ? <details><summary>Conflicting evidence</summary><pre style={{whiteSpace:'pre-wrap'}}>{JSON.stringify(r.conflicts,null,2)}</pre></details> : null}
  </div>;
}
