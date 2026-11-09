import NextAuth from "next-auth";
import authConfig from "./auth.config";
import { mutationBlocked } from "./lib/deployment-mutations";

const { auth } = NextAuth(authConfig);
export default auth((request) => {
  if (mutationBlocked(process.env, request.method, request.nextUrl.pathname)) {
    return Response.json(
      { error: "Mutating workflows are disabled in this deployment" },
      { status: 503 },
    );
  }
});
export const config = { matcher: ["/dashboard/:path*", "/targets/:path*", "/firms/:path*", "/research/:path*", "/outreach/:path*", "/changes/:path*", "/operations/:path*", "/data-dictionary/:path*", "/api/dashboard/:path*", "/api/targets/:path*", "/api/firms/:path*", "/api/research/:path*", "/api/sources/:path*", "/api/contacts/:path*", "/api/outreach/:path*", "/api/changes/:path*", "/api/operations/:path*", "/api/enrichment/:path*", "/api/research-agent/:path*", "/api/virtual-sdr/:path*", "/api/adv/:path*", "/api/seller-intent/:path*"] };
