export const dynamic = "force-dynamic";

import Link from "next/link";
import { redirect } from "next/navigation";
import { targetData } from "../../lib/queries";
import { auth } from "../../auth";
import { analystIdentity } from "../../lib/analyst-shortlist";
import Pagination from "../components/Pagination";
import SellerIntentStatus from "../components/SellerIntentStatus";
import TargetExplorerTable from "./TargetExplorerTable";

const money = (value:any) => value == null ? "Unknown" : `$${(Number(value) / 1e6).toFixed(1)}M`;
const pct = (value:any) => value == null ? "Unknown" : `${(Number(value) * 100).toFixed(1)}%`;
const priority = (value:any) => value ? String(value).replace("PRIORITY_", "") : "Unknown";
const Definition = ({children,text}:{children:React.ReactNode;text:string}) =>
  <span className="column-definition" tabIndex={0}><span>{children}</span><span className="definition-banner">{text}</span></span>;

type TargetParams = {
  q?:string; priority?:string; registration?:string; sellerIntent?:string; state?:string; aum?:string;
  representatives?:string; iapdFreshness?:string; iapdConflict?:string;
  iapdDisclosure?:string; sort?:string; page?:string;
};

export default async function Targets({searchParams}:{searchParams:Promise<TargetParams>}) {
  const p = await searchParams;
  const session = await auth();
  const analystId = analystIdentity(session);
  if (!analystId) redirect(`/login?callbackUrl=${encodeURIComponent("/targets")}`);
  const page = Math.max(1, Number(p.page) || 1);
  const [sortField="score", direction="desc"] = (p.sort || "score_desc").split("_");
  const sortOrder = direction === "asc" ? "asc" : "desc";
  const d = await targetData({
    analystId,
    search:p.q, priority:p.priority, registration:p.registration, sellerIntent:p.sellerIntent, state:p.state,
    aum:p.aum, representatives:p.representatives, iapdFreshness:p.iapdFreshness,
    iapdConflict:p.iapdConflict, iapdDisclosure:p.iapdDisclosure,
    sortField, sortOrder, page,
  });
  const filters:Record<string,string|undefined> = {
    q:p.q, priority:p.priority, registration:p.registration, sellerIntent:p.sellerIntent, state:p.state,
    aum:p.aum, representatives:p.representatives, iapdFreshness:p.iapdFreshness,
    iapdConflict:p.iapdConflict, iapdDisclosure:p.iapdDisclosure,
  };
  const activeFilterCount = Object.values(filters).filter(Boolean).length;
  const sortHref = (field:string) => {
    const next = sortField === field && sortOrder === "desc" ? "asc" : "desc";
    const query = new URLSearchParams();
    Object.entries({...filters, sort:`${field}_${next}`}).forEach(([key,value]) => { if (value) query.set(key,value); });
    return `/targets?${query}`;
  };
  const sortLabel = (field:string,label:string) =>
    <Link className="sort-link" href={sortHref(field)}>{label}{sortField === field ? (sortOrder === "asc" ? " ↑" : " ↓") : ""}</Link>;
  const paginationParams = {...filters, sort:`${sortField}_${sortOrder}`};

  return <>
    <div className="top"><div><h2>Target Explorer</h2><p className="muted">
      {d.total.toLocaleString()} filtered · {d.universeTotal.toLocaleString()} total firms · {activeFilterCount} active filter{activeFilterCount === 1 ? "" : "s"}
    </p></div></div>
    <form className="toolbar target-filters">
      <input name="q" defaultValue={p.q} placeholder="Search name or CRD" />
      <select name="priority" defaultValue={p.priority || ""}><option value="">All priorities</option><option value="PRIORITY_A">A</option><option value="PRIORITY_B">B</option><option value="PRIORITY_C">C</option></select>
      <select name="registration" defaultValue={p.registration || "registered"}><option value="registered">Registered firms</option><option value="sec">SEC only</option><option value="state">State only</option><option value="dual">SEC + state</option><option value="era">ERA only</option><option value="all">All source firms</option></select>
      <select name="aum" defaultValue={p.aum || ""}><option value="">All AUM</option><option value="under200">Under $200M</option><option value="unknown">AUM unknown</option></select>
      <input name="state" defaultValue={p.state} placeholder="State" maxLength={2} aria-label="State" />
      <select name="representatives" defaultValue={p.representatives || ""}><option value="">All rep counts</option><option value="any">Has representatives</option><option value="none">No representatives</option><option value="1to3">1–3 representatives</option><option value="4plus">4+ representatives</option></select>
      <select name="iapdFreshness" defaultValue={p.iapdFreshness || ""}><option value="">All IAPD freshness</option><option value="monthly_confirmed">Monthly confirmed</option><option value="live_confirmed">Live confirmed</option><option value="partial">Partial or stale</option><option value="conflict">Conflict</option><option value="missing">Missing</option></select>
      <select name="sellerIntent" defaultValue={p.sellerIntent || ""}><option value="">All seller intent</option>{["UNKNOWN","SIGNAL_IDENTIFIED","DIRECTLY_EXPRESSED","ENGAGED_IN_DISCUSSION","FORMAL_PROCESS","NOT_INTERESTED","STALE","CONFLICTING"].map(status => <option key={status}>{status}</option>)}</select>
      <label className="filter-check"><input type="checkbox" name="iapdConflict" value="1" defaultChecked={p.iapdConflict === "1"} /> Conflicts only</label>
      <label className="filter-check"><input type="checkbox" name="iapdDisclosure" value="1" defaultChecked={p.iapdDisclosure === "1"} /> Rep disclosures</label>
      <button>Apply</button><Link className="button-link secondary" href="/targets">Reset</Link>
    </form>
    <TargetExplorerTable rows={d.rows} sortField={sortField} sortOrder={sortOrder} filters={filters} />
    <div className="panel table-wrap target-table target-table-pagination">
      <Pagination path="/targets" page={d.page} pageSize={d.pageSize} total={d.total} params={paginationParams} />
    </div>
  </>;
}
