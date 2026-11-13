"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import SellerIntentStatus from "../components/SellerIntentStatus";
import TargetColumnControls, { targetColumns, type TargetColumn } from "./TargetColumnControls";

type Preferences = { order: TargetColumn[]; hidden: TargetColumn[] };
type Props = { rows: any[]; sortField: string; sortOrder: string; filters: Record<string, string | undefined> };
const money = (value: any) => value == null ? "Unknown" : `$${(Number(value) / 1e6).toFixed(1)}M`;
const pct = (value: any) => value == null ? "Unknown" : `${(Number(value) * 100).toFixed(1)}%`;
const priority = (value: any) => value ? String(value).replace("PRIORITY_", "") : "Unknown";

function Definition({ children, text }: { children: React.ReactNode; text: string }) {
  return <span className="column-definition" tabIndex={0}><span>{children}</span><span className="definition-banner">{text}</span></span>;
}

export default function TargetExplorerTable({ rows, sortField, sortOrder, filters }: Props) {
  const [preferences, setPreferences] = useState<Preferences>({ order: targetColumns.map(([key]) => key), hidden: [] });
  const onPreferencesChange = useCallback((next: Preferences) => setPreferences(next), []);
  const sortLabel = (field: string, label: string) => {
    const direction = sortField === field && sortOrder === "desc" ? "asc" : "desc";
    const query = new URLSearchParams();
    Object.entries({ ...filters, sort: `${field}_${direction}` }).forEach(([key, value]) => { if (value) query.set(key, value); });
    return <Link className="sort-link" href={`/targets?${query}`}>{label}{sortField === field ? (sortOrder === "asc" ? " ↑" : " ↓") : ""}</Link>;
  };
  const headers: Record<TargetColumn, React.ReactNode> = {
    firm: <>Firm <small>{sortLabel("state", "State")}</small></>, priority: sortLabel("priority", "Priority"), score: sortLabel("score", "Score"), aum: sortLabel("aum", "AUM"),
    discretionaryAum: "Disc. AUM", hnw: "Ind./HNW", accounts: sortLabel("accounts", "Accts."), employees: sortLabel("employees", "Empl."), representatives: sortLabel("representatives", "Reps"),
    iapd: <Definition text="Monthly confirmed uses the latest compilation baseline. Partial may be incomplete or stale. Conflict preserves disagreeing monthly and live evidence.">IAPD</Definition>,
    research: <Definition text="NOT_STARTED means external research has not yet been recorded for the firm.">Research</Definition>,
    sellerIntent: <Definition text="Evidence-backed willingness or process status. UNKNOWN means no verified seller-intent evidence.">Seller intent</Definition>,
    outreach: <Definition text="Outreach tracks preparation and activity; it does not send messages.">Outreach</Definition>,
  };
  const value = (row: any, key: TargetColumn): React.ReactNode => {
    switch (key) {
      case "firm": return <><Link href={`/firms/${row.firm_id}`}>{row.name || row.firm_id}</Link><br/><small className="muted">CRD {row.firm_id} · {row.organization_state || "Unknown"}</small></>;
      case "priority": return <span className={`badge ${row.priority_category === "PRIORITY_A" ? "good" : ""}`}>{priority(row.priority_category)}</span>;
      case "score": return row.acquisition_score == null ? "Unknown" : Number(row.acquisition_score).toFixed(1);
      case "aum": return money(row.total_aum);
      case "discretionaryAum": return pct(row.discretionary_aum != null && row.total_aum != null && Number(row.total_aum) !== 0 ? Number(row.discretionary_aum) / Number(row.total_aum) : null);
      case "hnw": return pct(row.individual_hnw_share);
      case "accounts": return row.total_account_count == null ? "Unknown" : Number(row.total_account_count).toLocaleString();
      case "employees": return row.employee_count == null ? "Unknown" : row.employee_count;
      case "representatives": return <>{row.representative_count == null ? "Unknown" : row.representative_count}{Number(row.representative_with_disclosure_count) > 0 ? <small className="flag-line">Disclosure flag</small> : null}</>;
      case "iapd": return <><span className={`badge ${row.iapd_freshness === "conflict" ? "warn" : row.iapd_freshness === "monthly_confirmed" ? "good" : ""}`}>{String(row.iapd_freshness || "missing").replaceAll("_", " ")}</span>{row.iapd_snapshot_date ? <small className="flag-line">{row.iapd_snapshot_date}</small> : null}</>;
      case "research": return row.research_status || "NOT_STARTED";
      case "sellerIntent": return <SellerIntentStatus status={row.seller_intent_status} compact />;
      case "outreach": return row.outreach_status || "NOT_RESEARCHED";
    }
  };
  const visible = preferences.order.filter(key => !preferences.hidden.includes(key));

  return <div className="target-table-tools">
    <TargetColumnControls onChange={onPreferencesChange} />
    <div className="panel table-wrap target-table"><table><thead><tr>{visible.map(key => <th key={key}>{headers[key]}</th>)}</tr></thead><tbody>
      {rows.map(row => <tr key={`${row.firm_id}:${row.dataset_version}`}>{visible.map(key => <td key={key}>{value(row, key)}</td>)}</tr>)}
    </tbody></table></div>
  </div>;
}
