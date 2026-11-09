import { validateVercelDeployment } from "../lib/deployment-policy.ts";

try {
  const result = validateVercelDeployment(process.env);
  process.stdout.write(`${JSON.stringify({ status: "passed", ...result }, null, 2)}\n`);
} catch (error) {
  process.stderr.write(`${JSON.stringify({
    status: "blocked",
    reason: error instanceof Error ? error.message : "Vercel deployment validation failed",
  })}\n`);
  process.exitCode = 1;
}
