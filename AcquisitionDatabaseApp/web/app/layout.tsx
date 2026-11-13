import "./globals.css";
import AppNavigation from "./components/AppNavigation";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body><div className="shell"><aside className="nav"><h1>SCM RIA Intelligence</h1><AppNavigation /></aside><main className="main">{children}</main></div></body></html>;
}
