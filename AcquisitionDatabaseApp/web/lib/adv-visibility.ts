// Shared presentation rules. A missing filing or failed extraction is never a negative answer.
export type Evidence = { review_status?: string | null; [key: string]: unknown };
export const present = (value: unknown): boolean => value != null && String(value).trim() !== "";
export const yesNo = (value: unknown): string => value === true ? "Yes" : value === false ? "No" : "Unknown";

export function evidenceStatus(rows: Evidence[] = []): string {
  if (rows.some(row => ["PROPOSED", "CONFLICTING", "NEEDS_REVIEW"].includes(row.review_status || ""))) return "Review";
  if (rows.some(row => row.review_status === "ACCEPTED")) return "Available";
  return "Unavailable";
}

export function custodianStatus(required: unknown, rows: Evidence[] = []): string {
  const status = evidenceStatus(rows);
  if (status === "Review") return status;
  if (status === "Available") return required === false ? "Review" : "Reported";
  return required === false ? "Not required" : "Unavailable";
}

export function officeStatus(office: Record<string, unknown> = {}): string {
  const fields = ["street_address_1", "city", "country"];
  // Region and postal conventions vary internationally; never invent a state.
  if (["US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"].includes(String(office.main_office_country || "").trim().toUpperCase())) fields.push("state", "postal_code");
  if (fields.every(key => present(office[`main_office_${key}`]))) return "Complete";
  return ["street_address_1", "street_address_2", "city", "state", "postal_code", "country"].some(key => present(office[`main_office_${key}`])) ? "Partial" : "Unavailable";
}

export function officeLines(office: Record<string, unknown> = {}): string[] {
  const text = (key: string) => present(office[key]) ? String(office[key]).trim() : "";
  const locality = [text("main_office_city"), text("main_office_state")].filter(Boolean).join(", ");
  return [text("main_office_street_address_1"), text("main_office_street_address_2"), [locality, text("main_office_postal_code")].filter(Boolean).join(" "), text("main_office_country")].filter(Boolean);
}

export function advIndicators(row: any) {
  const observations: any[] = row.schedule_observations || [];
  const ownership = evidenceStatus(observations.filter(item => item.field_key === "adv.ownership_control"));
  return {
    succession_status: yesNo(row.succession_indicator),
    custodian_status: custodianStatus(row.sma_custodian_reporting_required, row.custodians || []),
    ownership_status: ownership === "Review" ? "Review" : row.has_principals || ownership === "Available" ? "Available" : "Unavailable",
    part2a_status: evidenceStatus(observations.filter(item => item.field_key === "adv.brochure_intelligence")),
    office_contact_status: officeStatus(row),
    phone_available: present(row.main_office_phone),
  };
}

export const advIndicatorDefinitions: Record<string, string> = {
  succession_status: "Item 4 reports succession to an advisory business at this filing. No does not rule out a previously reported succession or establish seller intent.",
  custodian_status: "Reported: accepted custodian evidence. Review: proposed or conflicting evidence. Not required: the structured filing reports no applicable reporting requirement. Unavailable: detail has not been established.",
  ownership_status: "Available means reported Schedule A/B principals or accepted evidence exists; it does not establish beneficial ownership or founder status. Review means evidence remains proposed or conflicting.",
  part2a_status: "Available means accepted brochure facts exist. Review means proposed or conflicting facts exist. A document link alone does not mean its contents have been parsed.",
  office_contact_status: "Complete means street, city and country are present, plus state and postal code for U.S. offices. Partial means some address fields are missing. Phone coverage is shown separately.",
  phone_available: "Availability of the main-office telephone reported in the firm's filing, not a representative's personal telephone.",
};
