import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";
import { randomUUID } from "node:crypto";
import bcrypt from "bcryptjs";
import pg from "pg";

if (!process.env.DATABASE_URL) throw new Error("DATABASE_URL is required");

const prompt = createInterface({ input: stdin, output: stdout });
const pool = new pg.Pool({ connectionString: process.env.DATABASE_URL });
try {
  const email = (await prompt.question("Analyst email: ")).trim().toLowerCase();
  const name = (await prompt.question("Analyst name: ")).trim() || email;
  const password = await prompt.question("Temporary password (input is visible): ");
  if (!email || !password || password.length < 12) throw new Error("Enter an email and a password of at least 12 characters");
  const passwordHash = await bcrypt.hash(password, 12);
  await pool.query(
    "insert into users (id, email, password_hash, name, role) values ($1, $2, $3, $4, 'analyst')",
    [randomUUID(), email, passwordHash, name],
  );
  console.log(`Created analyst account for ${email}.`);
} finally {
  prompt.close();
  await pool.end();
}
