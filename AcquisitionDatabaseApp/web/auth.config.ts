import type { NextAuthConfig } from "next-auth";
const developmentSecret = "scm-local-development-secret-change-before-production";
export default { providers: [], secret: process.env.AUTH_SECRET || (process.env.NODE_ENV === "production" ? undefined : developmentSecret), pages: { signIn: "/login" }, callbacks: { authorized: ({ auth }) => !!auth } } satisfies NextAuthConfig;
