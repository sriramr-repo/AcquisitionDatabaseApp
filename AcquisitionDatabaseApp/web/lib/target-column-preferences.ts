export const targetColumnKeys = [
  "firm", "priority", "score", "aum", "discretionaryAum", "hnw", "accounts",
  "employees", "representatives", "iapd", "research", "sellerIntent", "outreach",
] as const;

export type TargetColumnPreferences = { order: string[]; hidden: string[] };

export function sanitizeTargetColumnPreferences(value: unknown): TargetColumnPreferences | null {
  if (!value || typeof value !== "object") return null;
  const input = value as { order?: unknown; hidden?: unknown };
  if (!Array.isArray(input.order) || !Array.isArray(input.hidden)) return null;
  const valid = new Set<string>(targetColumnKeys);
  const order = [...new Set(input.order.filter((key): key is string => typeof key === "string" && valid.has(key)))];
  const hidden = [...new Set(input.hidden.filter((key): key is string => typeof key === "string" && valid.has(key) && key !== "firm"))];
  if (order.length !== targetColumnKeys.length || !targetColumnKeys.every(key => order.includes(key))) return null;
  return { order, hidden };
}
