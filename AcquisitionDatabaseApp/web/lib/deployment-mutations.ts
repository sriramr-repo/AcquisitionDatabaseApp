export type DeploymentEnvironment = "production" | "preview" | "development" | "local";
export type Environment = Record<string, string | undefined>;

const mutationMethods = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export function deploymentEnvironment(env: Environment): DeploymentEnvironment {
  const value = env.VERCEL_ENV;
  if (value === "production" || value === "preview" || value === "development") return value;
  return "local";
}

export function mutationsAllowed(env: Environment): boolean {
  const deployment = deploymentEnvironment(env);
  if (deployment === "preview") return false;
  if (deployment === "production") return env.SCM_MUTATIONS_ENABLED === "true";
  return env.SCM_MUTATIONS_ENABLED !== "false";
}

export function mutationBlocked(env: Environment, method: string, pathname: string): boolean {
  return pathname.startsWith("/api/") && mutationMethods.has(method.toUpperCase()) && !mutationsAllowed(env);
}
