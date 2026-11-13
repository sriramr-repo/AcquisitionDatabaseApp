import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import bcrypt from "bcryptjs";
import authConfig from "./auth.config";
import { pool } from "./lib/db";

export const { handlers, signIn, signOut, auth } = NextAuth({
  ...authConfig,
  session: { strategy: "jwt" },
  providers: [Credentials({
    credentials: { email: {}, password: {} },
    async authorize(credentials) {
      const email = String(credentials?.email || "").trim().toLowerCase();
      const password = String(credentials?.password || "");
      if (!email || !password) return null;

      // The users table supports analyst-specific identities and preferences.
      const stored = await pool.query<{ id: string; email: string; password_hash: string; name: string | null; role: string }>(
        "select id, email, password_hash, name, role from users where lower(email) = $1 limit 1",
        [email],
      );
      const user = stored.rows[0];
      if (user && await bcrypt.compare(password, user.password_hash)) {
        return { id: user.id, email: user.email, name: user.name || user.email, role: user.role };
      }

      // Preserve the existing single-account deployment credential during rollout.
      const configuredEmail = process.env.AUTH_DEV_EMAIL;
      const configuredHash = process.env.AUTH_DEV_PASSWORD_HASH;
      if (!configuredEmail || !configuredHash || email !== configuredEmail.trim().toLowerCase()) return null;
      if (!(await bcrypt.compare(password, configuredHash))) return null;
      return { id: email, email, name: email, role: "analyst" };
    },
  })],
  callbacks: { async session({ session, token }) { if (session.user) session.user.id = String(token.sub); return session; } },
});
