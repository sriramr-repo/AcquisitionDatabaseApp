import "./globals.css";
import Link from "next/link";
export default function Layout({ children }: { children: React.ReactNode }) { return <html lang="en"><body><div className="shell"><aside className="nav"><h1>SCM RIA Intelligence</h1><Link href="/dashboard">Overview</Link><Link href="/targets">Target Explorer</Link><Link href="/research">Research</Link><Link href="/outreach">Outreach</Link><Link href="/changes">Changes</Link><Link href="/operations">Operations</Link></aside><main className="main">{children}</main></div></body></html> }
