export type ShortlistAddRequest = { datasetVersion: string };

export function parseShortlistAddRequest(value: unknown): ShortlistAddRequest | null {
  if (!value || typeof value !== "object") return null;
  const datasetVersion = (value as { datasetVersion?: unknown }).datasetVersion;
  return typeof datasetVersion === "string" && datasetVersion.trim()
    ? { datasetVersion: datasetVersion.trim() }
    : null;
}

export function shortlistRequestMatchesActiveDataset(request: ShortlistAddRequest, activeDatasetVersion: string): boolean {
  return request.datasetVersion === activeDatasetVersion;
}

export function analystIdentity(session: { user?: { id?: unknown; email?: unknown } } | null | undefined): string | null {
  const id = typeof session?.user?.id === "string" ? session.user.id.trim() : "";
  if (id && id !== "undefined" && id !== "null") return id;
  const email = typeof session?.user?.email === "string" ? session.user.email.trim().toLowerCase() : "";
  return email || null;
}
