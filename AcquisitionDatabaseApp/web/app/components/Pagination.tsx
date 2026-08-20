import Link from "next/link";

export default function Pagination({ path, page, pageSize, total, params = {} }: { path: string; page: number; pageSize: number; total: number; params?: Record<string, string | undefined> }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  const href = (next: number) => {
    const query = new URLSearchParams();
    Object.entries({ ...params, page: String(next) }).forEach(([key, value]) => { if (value) query.set(key, value); });
    return `${path}?${query.toString()}`;
  };
  return <nav className="pagination" aria-label="Pagination"><span className="muted">Page {page} of {pages} · {total.toLocaleString()} firms</span><span className="pagination-actions">{page > 1 ? <Link href={href(page - 1)}>← Previous</Link> : <span className="pagination-disabled">← Previous</span>}{page < pages ? <Link href={href(page + 1)}>Next →</Link> : <span className="pagination-disabled">Next →</span>}</span></nav>;
}
