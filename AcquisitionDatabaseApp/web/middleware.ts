import NextAuth from "next-auth";
import authConfig from "./auth.config";
export const { auth: middleware } = NextAuth(authConfig);
export const config = { matcher: ["/dashboard/:path*", "/targets/:path*", "/firms/:path*", "/research/:path*", "/outreach/:path*", "/changes/:path*", "/operations/:path*", "/api/dashboard/:path*", "/api/targets/:path*", "/api/firms/:path*", "/api/research/:path*", "/api/sources/:path*", "/api/contacts/:path*", "/api/outreach/:path*", "/api/changes/:path*", "/api/operations/:path*", "/api/enrichment/:path*"] };
