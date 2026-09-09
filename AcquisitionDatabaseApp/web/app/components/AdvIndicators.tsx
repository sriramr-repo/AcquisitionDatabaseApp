import Link from "next/link";
import { advIndicatorDefinitions } from "../../lib/adv-visibility";

export default function AdvIndicators({ row }: { row: any }) {
  const entries = [
    ["Succession", "succession_status", "succession"],
    ["Custodian", "custodian_status", "custodians"],
    ["Ownership", "ownership_status", "ownership"],
    ["Part 2A", "part2a_status", "brochure"],
    ["Office", "office_contact_status", "main-office"],
    ["Phone", "phone_available", "main-office"],
  ];
  return <div className="adv-indicators" aria-label="ADV coverage">{entries.map(([label, key, anchor]) => {
    const status = key === "phone_available" ? row[key] ? "Available" : "Unavailable" : row[key] || "Unavailable";
    return <Link key={key} href={`/firms/${row.firm_id}#${anchor}`} title={advIndicatorDefinitions[key]} className={status === "Review" ? "needs-review" : undefined}><span>{label}</span><b>{status}</b></Link>;
  })}</div>;
}
