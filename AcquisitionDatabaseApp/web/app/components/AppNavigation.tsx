"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  ["/dashboard", "Overview"],
  ["/targets", "Target Explorer"],
  ["/research", "Research"],
  ["/outreach", "Outreach"],
  ["/changes", "Changes"],
  ["/operations", "Operations"],
  ["/data-dictionary", "Data Dictionary"],
] as const;

export default function AppNavigation() {
  const pathname = usePathname();

  return <nav className="nav-links" aria-label="Primary navigation">
    {items.map(([href, label]) => {
      const active = pathname === href || (href === "/dashboard" && pathname === "/");
      return <Link href={href} key={href} aria-current={active ? "page" : undefined}>{label}</Link>;
    })}
  </nav>;
}
