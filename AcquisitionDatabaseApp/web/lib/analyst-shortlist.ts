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
