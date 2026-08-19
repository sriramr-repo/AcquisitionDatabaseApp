import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import bcrypt from "bcryptjs";
import authConfig from "./auth.config";

export const { handlers, signIn, signOut, auth } = NextAuth({
  ...authConfig,
  session: { strategy: "jwt" },
  providers: [Credentials({
    credentials: { email: {}, password: {} },
    async authorize(credentials) {
      const email = String(credentials?.email || "");
      const password = String(credentials?.password || "");
      const configuredEmail = process.env.AUTH_DEV_EMAIL;
      const configuredHash = process.env.AUTH_DEV_PASSWORD_HASH;
      if (!configuredEmail || !configuredHash || email !== configuredEmail) return null;
      if (!(await bcrypt.compare(password, configuredHash))) return null;
      return { id: email, email, name: email, role: "analyst" };
    },
  })],
  callbacks: { async session({ session, token }) { if (session.user) session.user.id = String(token.sub); return session; } },
});
