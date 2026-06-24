#!/usr/bin/env node
/** Entry point: run the Edgecute MCP over stdio (for Cursor / Claude Code). */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { buildServer } from "./server.js";
import { loadConfig } from "./config.js";

async function main(): Promise<void> {
  const server = buildServer(loadConfig());
  const transport = new StdioServerTransport();
  await server.connect(transport);
  // stderr is safe for logs (stdout is the JSON-RPC channel).
  process.stderr.write("[edgecute-mcp] ready\n");
}

main().catch((err) => {
  process.stderr.write(`[edgecute-mcp] fatal: ${String(err)}\n`);
  process.exit(1);
});
