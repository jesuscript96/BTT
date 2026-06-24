/** Runtime configuration, read from the IDE/client environment. */
export interface EdgecuteConfig {
  apiBase: string;
  apiKey: string | undefined;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): EdgecuteConfig {
  return {
    apiBase: (env.EDGECUTE_API_BASE ?? "https://api.edgecute.com/v1").replace(/\/+$/, ""),
    apiKey: env.EDGECUTE_API_KEY,
  };
}
